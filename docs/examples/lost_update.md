# Lost update — a non-atomic read-modify-write race

**What this teaches:** how separating a read and a write into two distinct steps opens a window where another actor can slip in, making the two steps non-atomic and silently discarding an update.

## The bug

Actor A wants to increment a shared counter. It does this in two steps:

1. **Read** the current value into a local register.
2. **Write** the register + 1 back.

Actor B does the same. If the steps interleave like this:

```
A_read  → A sees x=0
B_read  → B sees x=0
A_write → x becomes 1
B_write → x becomes 1   ← B's write wins, A's increment is lost
```

both actors incremented, but the counter ends at 1, not 2. One increment vanished.

This is the **lost update** or **ABA problem** — the root cause of countless concurrency bugs in databases, counters, inventories, and account balances.

## The model

The state carries the shared counter `x` plus per-actor read registers (`a_reg`, `b_reg`) that hold a value once read and are cleared on write. The invariant says: once both actors are done, the counter must equal 2.

musil's BFS explores every interleaving of the four actions (`A_read`, `A_write`, `B_read`, `B_write`) and finds the one where both reads happen before either write.

```
Invariant violated: both-increments-counted
Trace:
  A_read   → a_reg=0
  B_read   → b_reg=0
  A_write  → x=1
  B_write  → x=1   ← counter should be 2
```

## The fix

Make test-and-increment a single atomic action. A single action cannot be interleaved — once its guard fires, the update happens before any other action runs. See [Producer–consumer](producer_consumer.md) for a direct follow-up on this same fix applied to a bounded buffer.

## Source

```python
--8<-- "examples/lost_update.py"
```

## Run it

```
python examples/lost_update.py
```

## See also

- [Producer–consumer](producer_consumer.md) — the same race on a bounded buffer, with the atomic fix demonstrated.
- [Bank transfer](bank_transfer.md) — a related race on multiple accounts, compounded by locking order.
- [Mutual exclusion (Peterson)](mutex.md) — the algorithmic solution to protecting a critical section.
