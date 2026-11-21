# Multi-environment composition: K8s + AWS + etcd simultaneously

**What this teaches:** `check_open` accepts any number of `EnvironmentSpec` objects and merges their
behaviors and guarantees into a single BFS. The checker explores every interleaving of platform
faults across all three environments at once.

## The scenario

A service writes config to etcd and data to S3, while running inside a Kubernetes cluster. Three
external systems can fault independently:

| Environment | Fault modeled |
|-------------|---------------|
| K8s         | Pod eviction (service goes to `"evicted"`) |
| AWS S3      | Request throttling (in-flight writes cancelled, service goes to `"throttled"`) |
| etcd        | Leader change (in-flight reads cancelled, service goes to `"no-leader"`) |

Each fault is expressed as an `EnvironmentSpec` using the pre-built factories from
`musil.environments`:

```python
k8s_env   = pod_eviction(can_evict=_can_evict, on_evict=_on_evict)
aws_env   = aws_api_faults(can_throttle=_can_throttle, on_throttle=_on_throttle)
etcd_env  = cluster_faults(can_leader_change=_can_leader_change, on_leader_change=_on_leader_change)

result = check_open(service, k8s_env, aws_env, etcd_env)
```

## What the BFS explores

The combined BFS explores every ordering of:
- the service's own actions (`start-s3-write`, `complete-s3-write`, `start-etcd-read`,
  `complete-etcd-read`, `recover`)
- K8s evicting the pod
- AWS throttling an in-flight write
- etcd triggering a leader election during an in-flight read

At no point does the checker assume faults happen in any particular order or at any particular time.
If a fault + partial-write + recovery sequence can violate an invariant, the BFS finds it.

## The invariants

```python
"not-permanently-failed":      s.status != "running" and s.retries >= 5
"no-pending-after-eviction":   s.status == "evicted" and (s.s3_writes_pending > 0 or ...)
```

With retry-with-backoff, both pass. The service recovers from each fault type within the retry
budget.

## Residual proof obligations

The pre-built environments ship with named `Assumption` objects citing the actual source (Kubernetes
docs, AWS SLA, the Raft paper). Those that are `"unverified"` surface in
`result.unverified_assumptions`. A machine-readable list of what the BFS cannot prove on its own.

## Source

```python
--8<-- "examples/open_system_composed.py"
```

## Run it

```
python examples/open_system_composed.py
```

## See also

- [K8s scheduler](k8s_scheduler.md): a standalone K8s example that shows the fragile vs. resilient
  contrast in detail.
- [Pre-built environments](../environments.md): full reference for `musil.environments.k8s`, `.aws`,
  `.etcd`, `.linux`, `.sel4`.
- [Open systems (conceptual guide)](../open-systems.md): the theory behind composing multiple
  `EnvironmentSpec` objects.
