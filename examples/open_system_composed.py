"""Multi-environment open-system verification example.

This example verifies a simple distributed service against three simultaneous
adversarial environments:

1. K8s pod eviction (scheduler can evict the pod at any time)
2. AWS throttling (the downstream S3 write may be throttled)
3. etcd leader change (the config store may be mid-election)

The service model implements retry-with-backoff for each fault type.
Without retries the model fails the invariant (stale config or missed writes).
With retries it passes — and the output lists the residual proof obligations.

Run::

    uv run python examples/open_system_composed.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check_open
from musil.environments.aws import aws_api_faults
from musil.environments.etcd import cluster_faults
from musil.environments.k8s import pod_eviction

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServiceState:
    """State of a service that writes config to etcd and data to S3."""

    status: str = "running"          # running | evicted | throttled | no-leader | recovering
    s3_writes_pending: int = 0
    etcd_reads_pending: int = 0
    retries: int = 0


# ---------------------------------------------------------------------------
# System actions
# ---------------------------------------------------------------------------

def start_s3_write(s: ServiceState) -> ServiceState:
    return replace(s, s3_writes_pending=s.s3_writes_pending + 1)


def complete_s3_write(s: ServiceState) -> ServiceState:
    return replace(s, s3_writes_pending=s.s3_writes_pending - 1)


def start_etcd_read(s: ServiceState) -> ServiceState:
    return replace(s, etcd_reads_pending=s.etcd_reads_pending + 1)


def complete_etcd_read(s: ServiceState) -> ServiceState:
    return replace(s, etcd_reads_pending=s.etcd_reads_pending - 1)


def recover(s: ServiceState) -> ServiceState:
    return replace(s, status="running", retries=s.retries + 1)


# ---------------------------------------------------------------------------
# System model
# ---------------------------------------------------------------------------

service = Model(
    init=ServiceState(),
    actions=[
        Action("start-s3-write",
               lambda s: s.status == "running" and s.s3_writes_pending < 2,
               start_s3_write),
        Action("complete-s3-write",
               lambda s: s.s3_writes_pending > 0 and s.status == "running",
               complete_s3_write),
        Action("start-etcd-read",
               lambda s: s.status == "running" and s.etcd_reads_pending < 2,
               start_etcd_read),
        Action("complete-etcd-read",
               lambda s: s.etcd_reads_pending > 0 and s.status == "running",
               complete_etcd_read),
        Action("recover",
               lambda s: s.status != "running" and s.retries < 5,
               recover),
    ],
    invariants={
        "not-permanently-failed": lambda s: not (s.status != "running" and s.retries >= 5),
        "no-pending-after-eviction": lambda s: not (
            s.status == "evicted" and (s.s3_writes_pending > 0 or s.etcd_reads_pending > 0)
        ),
    },
)


# ---------------------------------------------------------------------------
# Action predicates and transitions (named functions required for pyright strict)
# ---------------------------------------------------------------------------

def _can_evict(s: ServiceState) -> bool:
    return s.status == "running"


def _on_evict(s: ServiceState) -> ServiceState:
    return replace(s, status="evicted", s3_writes_pending=0, etcd_reads_pending=0)


def _can_throttle(s: ServiceState) -> bool:
    return s.s3_writes_pending > 0 and s.status == "running"


def _on_throttle(s: ServiceState) -> ServiceState:
    return replace(s, status="throttled", s3_writes_pending=0)


def _can_leader_change(s: ServiceState) -> bool:
    return s.etcd_reads_pending > 0 and s.status == "running"


def _on_leader_change(s: ServiceState) -> ServiceState:
    return replace(s, status="no-leader", etcd_reads_pending=0)


# ---------------------------------------------------------------------------
# Environment specs
# ---------------------------------------------------------------------------

k8s_env = pod_eviction(can_evict=_can_evict, on_evict=_on_evict)

aws_env = aws_api_faults(can_throttle=_can_throttle, on_throttle=_on_throttle)

etcd_env = cluster_faults(can_leader_change=_can_leader_change, on_leader_change=_on_leader_change)


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def main() -> None:
    result = check_open(service, k8s_env, aws_env, etcd_env)

    if result.ok:
        print("PASS  Service invariants hold under K8s + AWS + etcd faults.")
    else:
        print("FAIL  Invariant violated!")
        r = result.result
        if r.trace:
            for step in r.trace:
                print(f"  {step}")

    if result.unverified_assumptions:
        print("\nResidual proof obligations (must be verified externally):")
        for a in result.unverified_assumptions:
            tag = f"[{a.status}]"
            print(f"  {tag:12} {a.name}")
            print(f"               {a.description}")
            if a.source:
                print(f"               Source: {a.source}")
    else:
        print("\nNo residual proof obligations.")


if __name__ == "__main__":
    main()
