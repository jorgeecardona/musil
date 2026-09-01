# Pre-built Environments

musil ships a library of pre-built adversarial environments for common platform components.
Each module gives you named `Assumption` constants (citing real docs/papers), an
`EnvironmentSpec` factory for model checking with `check_open`, and an `AdversarialNode`
factory for simulation testing.

---

## Quick start

```python
from dataclasses import dataclass, replace
from musil import Action, Model
from musil.env import check_open
from musil.environments.k8s import pod_eviction

@dataclass(frozen=True)
class Worker:
    status: str = "running"
    retries: int = 0

def can_evict(s: Worker) -> bool:
    return s.status == "running"

def on_evict(s: Worker) -> Worker:
    return replace(s, status="evicted")

def can_retry(s: Worker) -> bool:
    return s.status != "running" and s.retries < 3

def on_retry(s: Worker) -> Worker:
    return replace(s, status="running", retries=s.retries + 1)

def retries_exhausted(s: Worker) -> bool:
    return s.status != "running" and s.retries >= 3

model = Model(
    init=Worker(),
    actions=[Action("retry", can_retry, on_retry)],
    invariants={"alive": lambda s: s.status != "failed"},
    terminal=retries_exhausted,
)
env = pod_eviction(can_evict=can_evict, on_evict=on_evict)
result = check_open(model, env)

if result.ok:
    print("PASS")
else:
    print("FAIL — counter-example:", result.result.trace)

for a in result.unverified_assumptions:
    print(f"[{a.status:10}] {a.name}: {a.source}")
```

---

## Available environments

### `musil.environments.k8s` — Kubernetes

Models Kubernetes pod scheduler faults.

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `k8s:node-capacity` | unverified | Kubernetes docs: Pod lifecycle § Disruptions |
| `k8s:scheduler-liveness` | unverified | Kubernetes docs: Scheduling, Preemption and Eviction |
| `k8s:eviction-rate-bounded` | unverified | Kubernetes docs: Configure a Disruption Budget |

**Factories:**

- `pod_eviction(*, can_evict, on_evict, can_oom_kill=None, on_oom_kill=None, extra_assumptions=None)`
  — `EnvironmentSpec` for pod eviction and optional OOM kills
- `eviction_notifier(*, msg="k8s:evict")` — `AdversarialNode` that replies to any message with an eviction notification
- `oom_notifier(*, msg="k8s:oom-kill")` — `AdversarialNode` for OOM kill

---

### `musil.environments.aws` — AWS

Models AWS API faults: throttling, timeouts.

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `aws:s3-eventual-delivery` | unverified | AWS docs: Amazon S3 > Strong consistency |
| `aws:region-availability` | unverified | AWS SLA: Compute Service Level Agreement |
| `aws:throttle-transient` | unverified | AWS docs: Error retries and exponential backoff |
| `aws:iam-correctness` | **verified** | AWS docs: IAM security |

**Factories:**

- `aws_api_faults(*, can_throttle, on_throttle, can_timeout=None, on_timeout=None, extra_assumptions=None)`
  — `EnvironmentSpec` for API failures
- `throttling_service(*, throttle_msg=...)` — `AdversarialNode` that returns ThrottlingException
- `timeout_service()` — `AdversarialNode` that drops all messages (silent timeout)

---

### `musil.environments.linux` — Linux kernel

Models Linux process and filesystem faults.

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `linux:oom-killer-bounded` | unverified | Linux kernel docs: admin-guide/mm/concepts § OOM killer |
| `linux:signal-delivery` | unverified | Linux man-pages: signal(7) |
| `linux:fs-rename-atomic` | **verified** | Linux man-pages: rename(2) |
| `linux:enospc-recoverable` | unverified | Operational assumption |

**Factories:**

- `process_faults(*, can_oom_kill, on_oom_kill, can_sigterm=None, on_sigterm=None, extra_assumptions=None)`
  — `EnvironmentSpec` for OOM kills and SIGTERM
- `fs_faults(*, can_enospc, on_enospc, extra_assumptions=None)`
  — `EnvironmentSpec` for ENOSPC filesystem errors
- `oom_notifier(*, msg="linux:oom-kill")` — `AdversarialNode`
- `signal_sender(*, signal="SIGTERM")` — `AdversarialNode`

---

### `musil.environments.sel4` — seL4 microkernel

Models seL4 capability and IPC faults. seL4's formal verification (Klein et al., SOSP 2009)
is explicitly represented through verified/axiom assumption statuses.

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `sel4:hardware-memory-safety` | **axiom** | Klein et al., SOSP 2009 § 2 (TCB) |
| `sel4:capability-integrity` | **verified** | Klein et al., SOSP 2009 § 4 |
| `sel4:ipc-liveness` | unverified | seL4 Reference Manual § 4 (IPC) |

`HARDWARE_MEMORY_SAFETY` is an *axiom* — seL4's proof rests on it but cannot prove it from
within the system. It surfaces in `OpenResult.unverified_assumptions` as a residual obligation.

`CAP_INTEGRITY` is *verified* by the formal proof — it does NOT appear in unverified assumptions.

**Factories:**

- `capability_revocation(*, can_revoke, on_revoke, can_ipc_timeout=None, on_ipc_timeout=None, extra_assumptions=None)`
  — `EnvironmentSpec` for capability revocation and IPC timeouts
- `cap_revocation_notifier(*, msg="sel4:cap-revoked")` — `AdversarialNode`

---

### `musil.environments.etcd` — etcd cluster

Models etcd cluster faults: leader election, write conflicts, compaction.

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `etcd:quorum-maintained` | unverified | etcd docs: Clustering guide |
| `etcd:bounded-leader-election` | unverified | etcd docs: Tuning § Time parameters |
| `etcd:unique-leader` | **verified** | Ongaro & Ousterhout, USENIX ATC 2014 § 5 (Safety) |
| `etcd:compaction-bounded` | unverified | etcd docs: Maintenance § History compaction |

`UNIQUE_LEADER` is verified by the Raft safety proof — it does NOT appear in unverified assumptions.

**Factories:**

- `cluster_faults(*, can_leader_change, on_leader_change, can_write_conflict=None, on_write_conflict=None, can_compaction=None, on_compaction=None, extra_assumptions=None)`
  — `EnvironmentSpec` for cluster faults
- `etcd_adversary(*, msg="etcd:leader-change")` — `AdversarialNode`

---

### `musil.environments.distributed` — stateful storage/state faults

The fault classes that dominate a stateful distributed system's incident history, parameterized over
model-supplied accessors (no assumed state shape).

**Assumptions:**

| Name | Status | Source |
|------|--------|--------|
| `distributed:credential-rotation-observed` | unverified | OAuth 2.0 access-token expiry (RFC 6749 §1.5); secret-rotation practice |
| `distributed:reality-eventually-sensed` | unverified | Read-repair / cache-invalidation practice |

**Factories:**

- `credential_rotation(*, can_rotate, on_rotate, extra_assumptions=None)` — `EnvironmentSpec` for a
  credential invalidated mid-flight.
- `record_reality_divergence(*, can_diverge, on_diverge, extra_assumptions=None)` — `EnvironmentSpec` for a
  cached RECORD ceasing to match REALITY (a restart, a cutover, a re-attached/empty volume). Both "stale
  view after restart" and "wrong/empty volume attached" are usages of this one factory.

Not shipped here on purpose: **message lost/reordered/duplicated** is already `musil.channels` +
`sim.NetworkModel` (reuse those); **grace-window races** couple to `bounded_clock` and are left downstream.

---

## Composing multiple environments

Pass multiple `EnvironmentSpec` objects to `check_open` — behaviors and assumptions are merged:

```python
from musil.env import check_open
from musil.environments.k8s import pod_eviction
from musil.environments.aws import aws_api_faults
from musil.environments.etcd import cluster_faults

result = check_open(
    my_model,
    pod_eviction(can_evict=..., on_evict=...),
    aws_api_faults(can_throttle=..., on_throttle=...),
    cluster_faults(can_leader_change=..., on_leader_change=...),
)
```

The BFS explores all interleavings of all environment behaviors. Assumptions from every
environment are collected into `result.unverified_assumptions`.

See [examples/open_system_composed.py](https://gitlab.com/jorgecardona/musil/-/blob/main/examples/open_system_composed.py) for a complete multi-environment example.

---

## Adding your own assumptions

Each factory accepts `extra_assumptions: dict[str, Assumption]`:

```python
from musil.env import Assumption
from musil.environments.k8s import pod_eviction

my_sla = Assumption(
    name="infra:pod-restart-sla",
    description="Ops team guarantees pod restarts complete within 60s",
    status="unverified",
    source="SLA doc rev 2024-Q3",
)

env = pod_eviction(
    can_evict=...,
    on_evict=...,
    extra_assumptions={my_sla.name: my_sla},
)
```

---

## Simulation with AdversarialNode

For deterministic simulation testing, wire `AdversarialNode` factories into your node map:

```python
from musil.sim import NetworkModel, simulate
from musil.environments.k8s import eviction_notifier

report = simulate(
    lambda: {
        "worker": MyWorkerNode(),
        "k8s": eviction_notifier(msg="k8s:evict"),
    },
    seeds=range(200),
    network=NetworkModel(loss_rate=0.05),
    max_steps=500,
    invariants={"worker-alive": lambda nodes: nodes["worker"].alive},
)
print(report)
```

For Byzantine payload corruption, use `NetworkModel(mutate=...)`:

```python
import random
from musil.sim import NetworkModel, simulate

def flip_bits(src: str, dst: str, payload: object) -> object | None:
    if src == "service" and isinstance(payload, int):
        return payload ^ 0xFF
    return payload

report = simulate(
    lambda: {"client": MyClient(), "service": MyService()},
    seeds=range(100),
    network=NetworkModel(mutate=flip_bits),
    ...
)
```
