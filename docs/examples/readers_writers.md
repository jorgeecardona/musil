# Readers–writers — safety holds, but a naive policy starves the writer

**What this teaches:** safety and liveness are separate properties. A lock can be perfectly safe (no corruption) and yet permanently deny access to a class of waiters — a bug `check` never finds because no invariant is violated, only a fairness condition.

## The lock

Many readers may hold the lock simultaneously. A writer needs exclusive access — no readers, no other writers. The safety invariant:

```python
"mutual-exclusion": lambda s: not (s.writing and s.readers > 0)
```

Both policies below pass this check. Safety is not the interesting question here.

## The two policies

**Reader-preference:** a new reader may enter as long as no writer is *currently writing*. This means a stream of arriving readers can pass the lock among themselves indefinitely, and a waiting writer never sees `readers == 0`.

**Writer-preference:** once a writer announces it is waiting (`writer_waiting = True`), no *new* reader may enter. Existing readers finish; the writer enters next.

## What musil finds

`check` on both models: **PASS** — mutual exclusion holds regardless of policy.

`check_liveness` with `goal=lambda s: s.writing` (does a writer ever write?):

- **Reader-preference** → **FAIL** — musil finds a fair cycle where readers keep entering and the writer is perpetually deferred. The lasso counterexample shows the cycle.
- **Writer-preference** → **PASS** — under the same fairness assumptions (`want_write`, `stop_read`, and `start_write` are eventually taken), the writer always eventually writes.

The fairness assumptions (`fair=[...]`) are essential. Without them, an unfair scheduler could also starve the writer under writer-preference — but that is a scheduler failure, not a protocol failure. With fairness, the policy difference is the only variable.

## Source

```python
--8<-- "examples/readers_writers.py"
```

## Run it

```
python examples/readers_writers.py
```

## See also

- [Mutual exclusion (Peterson)](mutex.md) — proves safety for a two-process mutex.
- [Dining philosophers](dining_philosophers.md) — a related liveness failure: deadlock instead of starvation.
- [Producer–consumer](producer_consumer.md) — liveness checked via `check_liveness` on the atomic model.
