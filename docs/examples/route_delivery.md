# Reconciliation under loss — design and implementation

**What this teaches:** how to close the loop between a model-checked design and real node code. `check` and `check_liveness` verify the *design*; `simulate` runs the *implementation* under a lossy, reordering network and holds it to the model via refinement. The fire-and-forget bug is caught with a reproducible seed.

## The story

A control plane pushes a route-table version to an agent over a flaky link. The agent applies last-writer-wins. Two guarantees are required:

- **Safety** — the agent never serves a version the control plane never sent.
- **Liveness** — the agent always eventually converges to the latest version.

## Layer 1: the design

The model is minimal — one action (`deliver`) advances the agent's `applied` version toward the control plane's `desired` version:

```python
Action("deliver", lambda s: s.applied < s.desired, lambda s: Spec(s.desired, s.desired))
```

`check` verifies no deadlock and no stale-or-invented version. `check_liveness` proves convergence: under fair delivery, `applied == desired` is always eventually reached.

```
safety (no stale/invented version, no deadlock): OK
liveness (converges under fair delivery):        OK
```

## Layer 2: the implementation

Two real `BaseNode` classes, not model actions:

- **ControlPlane** — pushes the version and, optionally, re-sends on a timer until acked.
- **Agent** — applies the max version seen and acks.

`simulate` runs both under a network that drops ~30 % of messages and reorders the rest (`NetworkModel(loss=0.3, min_latency=1, max_latency=3)`). The `snapshot` function maps node state back to `Spec`, and `model=build_model()` with `abstraction=lambda s: s` enables **refinement checking** — every simulation step must be a valid model step or a stutter.

### Fire-and-forget fails

Without the timer, the control plane sends once and never retries. If the single push is dropped, the agent never converges.

```
fire-and-forget push:
  BUG FOUND — liveness on seed 7: applied==desired never reached
  final world: Spec(desired=1, applied=0)  (reproduce with seeds=[7])
```

### Per-tick re-push converges

With `repush=True`, the control plane sends the version every 2 ticks until acked. No matter how many early pushes are dropped, the one that survives the healed link delivers the version.

```
per-tick re-push:
  converged AND refined the model on all 300 seeds
```

## Source

```python
--8<-- "examples/route_delivery.py"
```

## Run it

```
python examples/route_delivery.py
```

## See also

- [Partition + heal (VOPR style)](partition_heal.md) — the same convergence question under a *sustained* partition with a defined heal time, not just random per-message loss.
- [K8s scheduler](k8s_scheduler.md) — open-system verification: the platform itself can evict the node mid-delivery.
- [Byzantine service](byzantine_service.md) — what happens when the remote end sends wrong answers rather than just dropping messages.
