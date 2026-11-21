# Partition + heal: VOPR-style liveness after a fault lifts

**What this teaches:** the difference between *random message loss* (self-heals via retries) and a
*sustained partition or crash* (only recoverable after the fault ends). `FaultSchedule` expresses
the latter; a `goal` checks whether the system converges once the fault lifts.

## The question: does it make progress?

The FoundationDB/TigerBeetle school of simulation testing asks not just "is it safe?" but "does it
converge once things settle?" A system can be perfectly safe (never serving wrong data) but
permanently wedged, serving no data at all.

Random per-message loss (`NetworkModel(loss=0.3)`) cannot express this question: an unlucky sequence
of drops eventually heals by itself as retries pile up. A partition or crash is different. The
system can only recover *after the fault ends*.

## The three scenarios

### 1. Partition + fire-and-forget → WEDGED

A `FaultSchedule(partitions=(Partition(frozenset({("s", "r")}), start=0, end=10),))` blocks all `s →
r` messages for ticks 0–10. The fire-and-forget source sends once at startup. The single push is
eaten by the partition. After tick 10 the link heals, but no message was ever queued for replay. The
agent never converges.

```
partition + fire-and-forget : WEDGED  (kind=liveness, seed=...)
```

### 2. Partition + per-tick re-push → CONVERGES

With `repush=True`, the source re-sends every 2 ticks until acked. After the partition heals (tick
10), the next re-push lands. The agent applies it and acks. Goal reached.

```
partition + per-tick re-push: CONVERGES (50 seeds, all green)
```

### 3. Cold restart → LOST ON RESTART

A `FaultSchedule(crashes=(Crash(node="r", start=3, end=8, lose_state=True),))` crashes and
cold-restarts the replica between ticks 3 and 8. If the source already acked and stopped retrying,
the applied value is gone. The replica starts from 0 and never hears the value again.

```
crash (cold restart): LOST ON RESTART (kind=liveness, seed=...)
```

## Source

```python
--8<-- "examples/partition_heal.py"
```

## Run it

```
python examples/partition_heal.py
```

## See also

- [Reconciliation under loss](route_delivery.md): the same convergence question with random loss and
  a model-backed refinement check.
- [K8s scheduler](k8s_scheduler.md): open-system model checking where the platform can evict nodes,
  not just drop messages.
