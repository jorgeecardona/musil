# Mutual exclusion (Peterson) — a correct algorithm, proved

**What this teaches:** how exhaustive interleaving can *prove* a concurrency algorithm correct — not just test it. Peterson's algorithm is the textbook example of a provably correct mutex.

## The algorithm

Two processes share a critical section. They coordinate using two boolean flags (`flag0`, `flag1`) and a tie-breaking `turn` variable. Each process follows four steps:

| Step | Action |
|------|--------|
| `p0_set` | Raise my flag: `flag0 = True`, advance to `"want"` |
| `p0_turn` | Yield the turn to the other: `turn = 1`, advance to `"wait"` |
| `p0_enter` | Enter the critical section once `flag1 is False` **or** `turn == 0` |
| `p0_exit` | Lower my flag: `flag0 = False`, return to `"idle"` |

Process 1 is symmetric (`flag1`, `turn = 0`, `turn == 1` test).

## What musil checks

The invariant is strict mutual exclusion:

```python
"mutual-exclusion": lambda s: not (s.pc0 == "crit" and s.pc1 == "crit")
```

musil explores **every** interleaving of the eight actions and finds no state where both processes are in the critical section simultaneously. No trace, no deadlock.

```
Result(ok=True, states_explored=...)
mutual exclusion holds across every interleaving
```

This is what "proof by model checking" means for bounded systems: the BFS is exhaustive, so "no violation found" is a guarantee, not a sample.

## Why this matters

Testing finds bugs only in the interleavings you happen to run. Peterson's algorithm is subtle — the `turn` variable is critical, and removing it silently breaks the invariant in specific interleavings that are hard to trigger by hand. musil finds those interleavings automatically.

## Source

```python
--8<-- "examples/mutex.py"
```

## Run it

```
python examples/mutex.py
```

## See also

- [Lost update](lost_update.md) — what happens *without* mutual exclusion on a shared counter.
- [Readers–writers](readers_writers.md) — a more complex lock with both safety and liveness questions.
- [Dining philosophers](dining_philosophers.md) — deadlock when multiple locks must be acquired in sequence.
