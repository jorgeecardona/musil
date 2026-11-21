# K8s scheduler: open-system verification against pod eviction

**What this teaches:** a closed model always passes because it controls everything. `check_open`
adds an adversarial `EnvironmentSpec` whose `behaviors` the BFS explores exhaustively. Exposing
failures that only appear when the *platform* acts, not just the service.

## Closed vs. open systems

A **closed model** is self-contained. Every state transition is under the model's control. In
isolation, the service is correct by construction: it starts, runs, degrades, and recovers.

An **open model** admits external actors. A Kubernetes cluster can evict a running pod at any
moment. After a node goes unhealthy, during a rolling update, or because resource pressure triggers
the eviction controller. The service does not control when this happens.

`check_open(model, k8s_env)` merges the environment's `behaviors` (the eviction action) into the
BFS. Every possible eviction timing is explored. Including mid-startup, mid-recovery, and the very
first tick.

## Two versions of the environment

**Fragile**: eviction silently kills the service:

```python
def evict(s): return replace(s, status="unresponsive")
```

The availability invariant (`status != "unresponsive"`) is violated the moment K8s fires. musil
finds it immediately.

**Resilient**: eviction triggers a controlled restart:

```python
def evict(s): return replace(s, status="starting", restarts=s.restarts + 1)
```

The service re-enters the startup lifecycle. musil verifies the invariant holds across all reachable
states, including repeated evictions up to `max_restarts`.

## Residual proof obligations

Even the resilient service has assumptions it can't verify internally:

```
[unverified] node-capacity
             At least one schedulable node is always available after eviction
[unverified] eviction-rate-bounded
             Eviction rate is bounded so max_restarts is not exceeded in practice
```

These surface as `unverified_assumptions` in the `OpenResult`. They are now explicit proof
obligations, not silent hypotheses buried in documentation.

## Source

```python
--8<-- "examples/k8s_scheduler.py"
```

## Run it

```
python examples/k8s_scheduler.py
```

## See also

- [Open systems (conceptual guide)](../open-systems.md): the theory behind `EnvironmentSpec`,
  `check_open`, and `Assumption`.
- [Multi-environment composition](open_system_composed.md): the same service verified against K8s +
  AWS + etcd simultaneously.
- [Pre-built environments](../environments.md): ready-made `EnvironmentSpec` objects for K8s, AWS,
  Linux, seL4, and etcd.
