# A textbook of concurrency and distributed systems

The examples in musil are not a grab-bag. Concurrency and distributed systems have a *canon* — a
fixed set of classic problems, and almost every one is bounded, state-machine-shaped, and driven by
**ordering or failure** rather than by input. That is exactly musil's diet. So `examples/` is an
**executable textbook**: each chapter is a classic problem modelled as states + guarded transitions +
invariants, where musil *finds* the classic bug and *verifies* the classic fix.

Each chapter does double duty — it is documentation (read it to learn the problem) and a test of
musil itself (each classic exercises a different feature: deadlock, fairness, channels, composition,
crash-recovery). **The full source of every completed chapter is embedded below**, inlined straight
from the runnable file in `examples/`; run any of them with `python examples/<name>.py`.

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

Every chapter follows the same four beats — the loop the **Reconciliation under loss** example
(below) demonstrates end to end:

1. **Design** — describe the protocol as a small state machine: a frozen dataclass plus guarded
   actions.
2. **Model the error** — inject the fault (a race via interleaving, or loss / crash / partition).
   musil returns the *shortest* counterexample: the exact sequence that breaks the invariant.
3. **Prevent** — change the design until the invariant holds across every reachable state.
4. **Guard** — keep the model (and, for real code, `simulate` / `check_refinement`) as a permanent
   regression test.

## The worked examples

In reading order, simplest first — finite-state machines, then shared-memory races, then mutual
exclusion, liveness, deadlock, and finally a distributed protocol checked design-and-implementation.

### Traffic light — the minimal finite-state machine

The smallest possible model: a three-state cycle. `check` sweeps every reachable state and confirms
the colour invariant holds.

```python
--8<-- "examples/traffic_light.py"
```

### Service lifecycle — a model straight from a transition table (zero drift)

Build the model directly from an allowed-transitions table with `status_field_actions`, so the spec
*is* the code's table and can't drift from it. `check` confirms every declared state is reachable
with no deadlock.

```python
--8<-- "examples/service_lifecycle.py"
```

### Lost update — a non-atomic increment race

Two actors each read-then-write a shared counter as separate steps. The interleaving sweep finds the
order where both read the stale value before either writes, so one increment is silently lost.

```python
--8<-- "examples/lost_update.py"
```

### Producer–consumer — the bounded-buffer check-then-act race

The room-check and the insert are separate steps, so two producers can both pass the "there is room"
check and overflow a one-slot buffer. The atomic test-and-insert stays within capacity and converges.

```python
--8<-- "examples/producer_consumer.py"
```

### Mutual exclusion (Peterson) — a correct mutex, proved

The classic mutual-exclusion algorithm, proved correct by exhaustive interleaving: the two processes
are never in the critical section together, and the protocol can't deadlock.

```python
--8<-- "examples/mutex.py"
```

### Readers–writers — safety holds, but a naive policy starves the writer

Mutual exclusion holds for both policies; the temporal question is liveness. Reader-preference lets
readers hand the lock among themselves forever and starve a waiting writer — a fair cycle musil finds
— while writer-preference drains the readers and lets the writer in.

```python
--8<-- "examples/readers_writers.py"
```

### Dining philosophers — the circular-wait deadlock

Everyone grabbing their left fork first wedges in a circular wait; musil reports the deadlock with
the shortest path into it. The resource-ordering rule (take the lower-numbered fork first) removes it.

```python
--8<-- "examples/dining_philosophers.py"
```

### Bank transfer — a lock-ordering deadlock and a conservation law

Two transfers locking their accounts in opposite order deadlock; locking in a fixed global order
fixes it, and the conservation invariant — money is neither created nor destroyed — holds throughout.

```python
--8<-- "examples/bank_transfer.py"
```

### Reconciliation under loss — design *and* implementation

The full loop: model-check a control-plane/agent protocol for safety and convergence, then run the
*real* event-driven node code under a lossy, reordering network with `simulate`, held to the same
model by refinement. The fire-and-forget push is caught with a reproducible seed; the per-tick
re-push converges on every seed.

```python
--8<-- "examples/route_delivery.py"
```

## On the roadmap

The chapters still to write — each forces a musil feature the examples above don't yet exercise.

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
textbook" writes the documentation *and* exhaustively exercises the tool — the same keystrokes.
