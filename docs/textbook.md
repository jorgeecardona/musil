# A textbook of concurrency and distributed systems

The examples in musil are not a grab-bag. Concurrency and distributed systems have a *canon* — a
fixed set of classic problems, and almost every one is bounded, state-machine-shaped, and driven by
**ordering or failure** rather than by input. That is exactly musil's diet. So `examples/` is meant
to grow into an **executable textbook**: each chapter is a classic problem modelled as states +
guarded transitions + invariants, where musil *finds* the classic bug and *verifies* the classic
fix.

Each chapter does double duty — it is documentation (read it to learn the problem) and a test of
musil itself (each classic exercises a different feature: deadlock, fairness, channels, composition,
crash-recovery). The textbook is also musil's own coverage matrix.

## When musil is the right tool

A model checker earns its keep when correctness depends on *what happened and in what order*, not on
*what the input was*. The dividing line:

> **Is the bug a function of the input, or a function of history and ordering?**
> Input / pure logic → a decision procedure (SAT / SMT / BDD).
> History / ordering / concurrency / failure → a model checker.

A stateless rule table ("does this packet match?") is the first kind — the wrong tool, because the
question is quantified over *inputs*, not over reachable states. A protocol that can race, reorder,
drop, partition, or wedge is the second kind — musil's home.

## How a chapter is built

Every chapter follows the same four beats — the loop the worked example
[`route_delivery.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/route_delivery.py)
demonstrates end to end:

1. **Design** — describe the protocol as a small state machine: a frozen dataclass plus guarded
   actions.
2. **Model the error** — inject the fault (a race via interleaving, or loss / crash / partition).
   musil returns the *shortest* counterexample: the exact sequence that breaks the invariant.
3. **Prevent** — change the design until the invariant holds across every reachable state.
4. **Guard** — keep the model (and, for real code, `simulate` / `check_refinement`) as a permanent
   regression test.

## The chapters

Legend: ✓ written · ○ planned.

### Shared-memory concurrency

| Problem | What it teaches | musil feature | Status |
|---|---|---|---|
| Producer–consumer / bounded buffer | check-then-act race overflows capacity | interleaving, conservation invariant | ✓ [`producer_consumer.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/producer_consumer.py) |
| Lost update | two non-atomic increments drop a write | interleaving | ✓ [`lost_update.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/lost_update.py) |
| Mutual exclusion (Peterson) | a correct mutex, proved over every interleaving | safety, no-deadlock | ✓ [`mutex.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/mutex.py) |
| Readers–writers | writer exclusion; reader/writer starvation | liveness, fairness | ○ |
| Dining philosophers | deadlock and starvation | deadlock detection, liveness | ○ |
| Bank transfer | conservation under concurrent transfers; lock-order deadlock | interleaving, deadlock | ○ |

### Agreement & coordination

| Problem | What it teaches | musil feature | Status |
|---|---|---|---|
| Two generals | agreement is impossible over a lossy link | liveness fails under loss | ○ |
| Two-/three-phase commit | atomic commit; the coordinator-failure blocking problem | channels, crash | ○ |
| Leader election | at most one leader, and eventually a leader | safety + liveness | ○ |
| Single-decree consensus (Paxos/Raft) | never decide two different values | composition, safety | ○ |
| Distributed lock + fencing | an expired lock that still acts | channels, safety | ○ |

### Replication & consistency

| Problem | What it teaches | musil feature | Status |
|---|---|---|---|
| Quorum (Dynamo) | read-after-write holds iff W + R > N | composition | ○ |
| Primary–backup | ack-before-replicate durability under failover | crash, refinement | ○ |
| CRDTs (G-counter, OR-set, LWW-register) | convergence / strong eventual consistency | composition | ○ |
| Reconciliation under loss | desired vs applied converges despite drops | design + simulation | ✓ [`route_delivery.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/route_delivery.py) |

### Messaging patterns

| Problem | What it teaches | musil feature | Status |
|---|---|---|---|
| At-least-once queue + visibility timeout | the double-process race; exactly-once is a fiction | channels, timers, simulation | ○ |
| Outbox / dual-write | making a db-write and a publish atomic | crash | ○ |
| Idempotent receiver | dedup makes redelivery safe | channels, duplication | ○ |
| Failure detector / heartbeat | dead-vs-slow under partition | timers, partition | ○ |

### State machines & coherence

| Problem | What it teaches | musil feature | Status |
|---|---|---|---|
| Service lifecycle (zero-drift) | a model built straight from an allowed-transitions table | fsm bridge | ✓ [`service_lifecycle.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/service_lifecycle.py) |
| Traffic light | the minimal finite-state machine | safety | ✓ [`traffic_light.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/traffic_light.py) |
| TCP handshake / teardown | half-open connections, simultaneous close | safety | ○ |
| Token ring | exactly one token; token loss and regeneration | safety, liveness | ○ |
| Cache coherence (MESI) | no two caches hold one line in *Modified* | composition, safety | ○ |

## The payoff

The canon is also the feature-coverage matrix. Each classic forces a different part of musil into
existence and hardens it: dining philosophers and bank transfer drive **deadlock**; readers–writers
and leader election drive **fairness / liveness**; two-phase commit and broadcast drive
**channels**; Paxos and replication drive **composition**; durability and primary–backup drive
**crash-recovery**; split-brain and the failure detector drive **partition**. So "implement the
textbook" writes the documentation *and* exhaustively exercises the tool — the same keystrokes.
