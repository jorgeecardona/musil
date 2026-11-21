# Producer–consumer: the bounded-buffer check-then-act race

**What this teaches:** splitting a guard into a separate "check" step and a later "commit" step lets
the guard go stale; the fix is a single atomic test-and-insert. As a bonus, `check_liveness`
verifies that every produced item is eventually consumed.

## The bug: check-then-act

A producer adds to a buffer of capacity 1. The naive protocol has two steps:

1. **Check**: if there is room (`count < CAP`), advance to the `ready` phase.
2. **Commit**: insert the item (`count += 1`), regardless of whether room still exists.

With two producers and a buffer of size 1, musil finds this interleaving:

```
P0_check  → P0 sees count=0, enters "ready"
P1_check  → P1 sees count=0, enters "ready"    ← both think there is room
P0_commit → count becomes 1
P1_commit → count becomes 2  ← OVERFLOW: buffer capacity is 1
```

The `within-capacity` invariant (`0 ≤ count ≤ CAP`) is violated.
This is [lost_update](lost_update.md) grown into a real data structure.

## The fix: atomic test-and-insert

Merge the check and the commit into a single `P{i}_put` action. The guard and the update happen
atomically. No other action can interleave between them.

```python
Action(
    f"P{i}_put",
    lambda s, _i=i: s.producers[_i] == "idle" and s.count < CAP,
    lambda s, _i=i: replace(s, count=s.count + 1, producers=_set(s.producers, _i, "done")),
)
```

musil verifies the fixed model for:

- **Safety**: `count` stays within `[0, CAP]` across every interleaving.
- **No deadlock**: the system always reaches a terminal state where all actors are done.
- **Liveness**: `check_liveness` proves every produced item is eventually consumed.

## Source

```python
--8<-- "examples/producer_consumer.py"
```

## Run it

```
python examples/producer_consumer.py
```

## See also

- [Lost update](lost_update.md): the simpler counter version of the same race.
- [Readers–writers](readers_writers.md): a liveness follow-up: safety holds but a naive policy
  starves the writer.
- [Bank transfer](bank_transfer.md): two transfers that deadlock because of locking order.
