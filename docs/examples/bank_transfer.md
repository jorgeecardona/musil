# Bank transfer: a lock-ordering deadlock and a conservation law

**What this teaches:** how locking two resources in opposite orders across concurrent actors
produces a circular wait (deadlock), and how a global lock order eliminates it. Together with a
conservation invariant that holds across every reachable state.

## The bug

Two transfers run concurrently:

- **t1**: moves a unit from account A to account B. Locks A first, then B.
- **t2**: moves a unit from account B to account A. Locks B first, then A.

The fatal interleaving:

```
t1_lock_a  → t1 holds lock A
t2_lock_b  → t2 holds lock B
t1_lock_b  → t1 waits for B (held by t2)
t2_lock_a  → t2 waits for A (held by t1)
```

Both transfers are now waiting for a lock the other holds. Deadlock.
musil reports it with the shortest path in. Four steps.

## The fix: global lock order

Require every transfer to lock the **lower-id account first**, regardless of the direction of the
transfer. With t2 also locking A before B:

```
t1_lock_a → t1 holds A
t2_lock_a → t2 waits for A (no circular dependency possible)
```

The circular wait is structurally impossible. Musil confirms no reachable deadlock.

## The conservation invariant

Beyond deadlock, musil also verifies that money is conserved: the total `a + b` never changes. This
invariant holds in every reachable state, including mid-transfer when one account has been debited
but the other not yet credited:

```python
invariants={"conservation": lambda s: s.a + s.b == TOTAL}
```

This is a stronger guarantee than "no deadlock". It says the *semantics* of the transfer are also
correct.

## Source

```python
--8<-- "examples/bank_transfer.py"
```

## Run it

```
python examples/bank_transfer.py
```

## See also

- [Dining philosophers](dining_philosophers.md): the same resource-hierarchy fix for forks instead
  of account locks.
- [Lost update](lost_update.md): a simpler concurrency bug where no lock is acquired at all.
- [Mutual exclusion (Peterson)](mutex.md): the mutual exclusion primitive that makes atomic sections
  possible.
