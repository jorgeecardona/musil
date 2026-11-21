# A textbook of concurrency and distributed systems

The examples in musil are not a grab-bag. Concurrency and distributed systems have a *canon*. A
fixed set of classic problems, and almost every one is bounded, state-machine-shaped, and driven by
**ordering or failure** rather than by input. That is exactly musil's diet. So `examples/` is an
**executable textbook**: each chapter is a classic problem modelled as states + guarded transitions +
invariants, where musil *finds* the classic bug and *verifies* the classic fix.

Each chapter does double duty. It is documentation (read it to learn the problem) and a test of
musil itself (each classic exercises a different feature: deadlock, fairness, channels, composition,
crash-recovery). Every completed chapter has its own page with a full walkthrough and the embedded
source; run any example directly with `python examples/<name>.py`.

## When musil is the right tool

A model checker earns its keep when correctness depends on *what happened and in what order*, not on
*what the input was*. The dividing line:

> **Is the bug a function of the input, or a function of history and ordering?**
> Input / pure logic → a decision procedure (SAT / SMT / BDD).
> History / ordering / concurrency / failure → a model checker.

A stateless rule table ("does this packet match?") is the first kind. The wrong tool, because the
question is quantified over *inputs*, not over reachable states. A protocol that can race, reorder,
drop, partition, or wedge is the second kind. Musil's home.

## How a chapter is built

Every chapter follows the same four beats:

1. **Design**: describe the protocol as a small state machine: a frozen dataclass plus guarded
   actions.
2. **Model the error**: inject the fault (a race via interleaving, or loss / crash / partition).
   musil returns the *shortest* counterexample: the exact sequence that breaks the invariant.
3. **Prevent**: change the design until the invariant holds across every reachable state.
4. **Guard**: keep the model (and, for real code, `simulate` / `check_refinement`) as a permanent
   regression test.

---

## Finite-state machines

The simplest models: a single state field, a handful of actions, one invariant.

| Example | Bug / lesson | musil feature |
|---------|-------------|---------------|
| [Traffic light](examples/traffic_light.md) | Minimal FSM; confirm the three-state cycle is safe | `check`, `to_dot` |
| [Service lifecycle](examples/service_lifecycle.md) | Build the model from the code's own transition table, so the two cannot differ | `status_field_actions`, `declared_states` |

---

## Shared-memory concurrency

Two or more actors share mutable state. The bug lives in the interleaving. A specific ordering that
no single-threaded test can find.

| Example | Bug / lesson | musil feature |
|---------|-------------|---------------|
| [Lost update](examples/lost_update.md) | Non-atomic read-modify-write; one increment silently lost | `check`, interleaving |
| [Producer–consumer](examples/producer_consumer.md) | Check-then-act race overflows a bounded buffer; atomic fix passes | `check`, `check_liveness` |
| [Mutual exclusion (Peterson)](examples/mutex.md) | Exhaustive proof that Peterson's algorithm is correct | `check`, invariant |
| [Readers–writers](examples/readers_writers.md) | Safety holds for both policies; reader-preference starves the writer | `check`, `check_liveness`, fairness |
| [Dining philosophers](examples/dining_philosophers.md) | Circular-wait deadlock; resource-ordering rule eliminates it | `check`, deadlock |
| [Bank transfer](examples/bank_transfer.md) | Lock-ordering deadlock; conservation invariant holds through the fix | `check`, invariant |
| [Vote tallying](examples/voting_tally.md) | Racy read-then-write count drops a vote; atomic count is correct. Ballot secrecy is *not* a model-checking property | `check`, invariant |

---

## Distributed protocols

Nodes that communicate over a network. Correctness depends on message ordering, loss, and failure.

| Example | Bug / lesson | musil feature |
|---------|-------------|---------------|
| [Reconciliation under loss](examples/route_delivery.md) | Fire-and-forget fails on a lossy link; re-push converges, verified by simulation + refinement | `simulate`, `check_refinement`, `check_liveness` |
| [Partition + heal](examples/partition_heal.md) | A sustained partition wedges fire-and-forget forever; cold restart loses un-retried writes | `simulate`, `FaultSchedule`, `Partition`, `Crash` |
| [Alternating Bit Protocol](examples/alternating_bit.md) | ABP is unsafe on an unordered link (it assumes FIFO); eventual delivery over loss needs strong, not weak, fairness | `channel_actions`, `check`, `check_liveness`, `fair_strong` |
| [Leader election](examples/leader_election.md) | No quorum → two leaders (split brain); a majority gives safety; electing a leader can split-vote livelock (why Raft needs randomized timeouts) | `check`, `check_liveness` |
| [Needham-Schroeder + Lowe's attack](examples/needham_schroeder.md) | A protocol believed correct for 17 years; `check` finds Lowe's 1995 man-in-the-middle attack as an authentication counterexample, and proves the fix clean | `check`, counterexample, bounded Dolev-Yao intruder |

---

## Open systems

Real systems interact with external actors (platforms, clouds, humans) that can behave
adversarially. `check_open` and `EnvironmentSpec` extend the BFS to include those behaviors.

| Example | Bug / lesson | musil feature |
|---------|-------------|---------------|
| [K8s scheduler](examples/k8s_scheduler.md) | Pod eviction violates availability unless the service restarts; residual obligations surfaced | `check_open`, `EnvironmentSpec`, `Assumption` |
| [Byzantine service](examples/byzantine_service.md) | Wrong answers and wire corruption; validation and mutation hooks catch both | `AdversarialNode`, `NetworkModel.mutate` |
| [Multi-environment composition](examples/open_system_composed.md) | K8s + AWS + etcd faults composed into a single BFS | `check_open` with multiple envs |
| [TCAS II](examples/tcas.md) | Four scenarios: correct coordination, Überlingen (pilot deviates), post-fix, Tenerife (v7.1 reversal) | `check_open`, `EnvironmentSpec`, `Assumption` |

---

## On the roadmap

The chapters still to write. Each forces a musil feature the examples above don't yet exercise.

### Agreement & coordination

| Problem | What it teaches | musil feature |
|---|---|---|
| Two generals | agreement is impossible over a lossy link | liveness fails under loss |
| Two-/three-phase commit | atomic commit; the coordinator-failure blocking problem | channels, crash |
| Leader election | at most one leader, and eventually a leader | safety + liveness |
| Single-decree consensus (Paxos/Raft) | never decide two different values | composition, safety |
| Distributed lock + fencing | an expired lock that still acts | channels, safety |

### Replication & consistency

| Problem | What it teaches | musil feature |
|---|---|---|
| Quorum (Dynamo) | read-after-write holds iff W + R > N | composition |
| Primary–backup | ack-before-replicate durability under failover | crash, refinement |
| CRDTs (G-counter, OR-set, LWW-register) | convergence / strong eventual consistency | composition |

### Messaging patterns

| Problem | What it teaches | musil feature |
|---|---|---|
| At-least-once queue + visibility timeout | the double-process race; exactly-once is a fiction | channels, timers, simulation |
| Outbox / dual-write | making a db-write and a publish atomic | crash |
| Idempotent receiver | dedup makes redelivery safe | channels, duplication |
| Failure detector / heartbeat | dead-vs-slow under partition | timers, partition |

### State machines & coherence

| Problem | What it teaches | musil feature |
|---|---|---|
| TCP handshake / teardown | half-open connections, simultaneous close | safety |
| Token ring | exactly one token; token loss and regeneration | safety, liveness |
| Cache coherence (MESI) | no two caches hold one line in *Modified* | composition, safety |

## The payoff

The canon is also the feature-coverage matrix. Each classic forces a different part of musil into
existence and hardens it: dining philosophers and bank transfer drive **deadlock**; readers–writers
and leader election drive **fairness / liveness**; two-phase commit and broadcast drive
**channels**; Paxos and replication drive **composition**; durability and primary–backup drive
**crash-recovery**; split-brain and the failure detector drive **partition**. So "implement the
textbook" writes the documentation *and* exhaustively exercises the tool. The same keystrokes.
