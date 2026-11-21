# Dining philosophers: the circular-wait deadlock

**What this teaches:** deadlock is a property of the reachable state space, not of any single
transition. It does not violate an invariant. It is a state with no enabled actions. musil reports
it with the shortest path in.

## The setup

N philosophers sit around a round table. Between each pair is a single fork. A philosopher needs
*both* adjacent forks to eat. The naive protocol: pick up your left fork, then your right.

With N = 3 (the smallest table that exhibits the problem):

| Philosopher | Left fork | Right fork |
|-------------|-----------|------------|
| P0          | fork 0    | fork 1     |
| P1          | fork 1    | fork 2     |
| P2          | fork 2    | fork 0     |

## The deadlock

If every philosopher picks up their left fork at the same moment, the table looks like:

```
P0 holds fork 0, waiting for fork 1
P1 holds fork 1, waiting for fork 2
P2 holds fork 2, waiting for fork 0
```

Everyone is waiting for a fork held by their neighbour. No one can proceed. No invariant is
violated; the system stops: no action is enabled. musil detects this as a **deadlock** (a
non-terminal state with no enabled action) and prints the shortest path into it.

## The fix: resource hierarchy

Break the circular wait by requiring every philosopher to pick up the **lower-numbered fork first**.
With this ordering, at least one philosopher always holds both forks in the correct order and can
eat.

```python
first, second = (min(left, right), max(left, right)) if ordered else (left, right)
```

musil confirms the ordered model has no reachable deadlock.

## Source

```python
--8<-- "examples/dining_philosophers.py"
```

## Run it

```
python examples/dining_philosophers.py
```

## See also

- [Bank transfer](bank_transfer.md): the same resource-hierarchy fix applied to account locks in a
  financial transaction.
- [Readers–writers](readers_writers.md): a liveness problem that looks like deadlock but is
  starvation instead.
- [Mutual exclusion (Peterson)](mutex.md): a protocol that correctly avoids both deadlock and
  starvation for two processes.
