"""Open-system model checking: a distributed service against K8s-like platform faults.

A *closed* system has no external components — the model controls everything. This example shows
the *open* system problem: a distributed service running inside a Kubernetes cluster where the
platform can evict pods or restrict network access at any moment.

``check`` on the closed model always passes (the service is correct in isolation). ``check_open``
adds a K8s ``EnvironmentSpec`` whose behaviors model platform faults. Without resilience, a pod
eviction moves the service to an "unresponsive" state — a silent violation of the availability
invariant. With resilience (the service restarts and re-registers), the same faults are survivable.

  python examples/k8s_scheduler.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check
from musil.env import Assumption, EnvironmentSpec, check_open


@dataclass(frozen=True)
class ServiceState:
    """State of a distributed service."""

    status: str          # "starting", "healthy", "degraded", "unresponsive"
    restarts: int = 0
    max_restarts: int = 3


def _service_model() -> Model[ServiceState]:
    """Service lifecycle: start → healthy → (degraded → healthy) loop.
    The system model is the same in both cases; resilience lives in the EnvironmentSpec.
    """
    def do_start(s: ServiceState) -> ServiceState:
        return replace(s, status="healthy")

    def do_degrade(s: ServiceState) -> ServiceState:
        return replace(s, status="degraded")

    def do_recover(s: ServiceState) -> ServiceState:
        return replace(s, status="healthy")

    def can_start(s: ServiceState) -> bool:
        return s.status == "starting"

    def can_degrade(s: ServiceState) -> bool:
        return s.status == "healthy"

    def can_recover(s: ServiceState) -> bool:
        return s.status == "degraded"

    def valid_status(s: ServiceState) -> bool:
        return s.status in {"starting", "healthy", "degraded", "unresponsive"}

    def availability_invariant(s: ServiceState) -> bool:
        # The core guarantee: the service must never reach "unresponsive" (silent failure).
        return s.status != "unresponsive"

    def restarts_bounded(s: ServiceState) -> bool:
        return s.restarts <= s.max_restarts

    return Model(
        init=ServiceState("starting"),
        actions=[
            Action("start",   can_start,   do_start),
            Action("degrade", can_degrade, do_degrade),
            Action("recover", can_recover, do_recover),
        ],
        invariants={
            "valid-status":          valid_status,
            "always-responsive":     availability_invariant,  # the key safety property
            "restarts-bounded":      restarts_bounded,
        },
    )


def _k8s_env(resilient: bool) -> EnvironmentSpec[ServiceState]:
    """K8s platform: can evict a running pod at any time.

    Without resilience: eviction silently moves the service to "unresponsive" — violates
    the availability invariant.

    With resilience: eviction triggers a controlled restart (increments restart counter)
    and re-enters "starting" — the service recovers. Fails only if restarts are exhausted.
    """
    if resilient:
        def evict(s: ServiceState) -> ServiceState:
            # Resilient: pod eviction triggers a restart (re-enters starting lifecycle).
            return replace(s, status="starting", restarts=s.restarts + 1)
    else:
        def evict(s: ServiceState) -> ServiceState:
            # Fragile: pod eviction silently kills the service → unresponsive (violates availability).
            return replace(s, status="unresponsive")

    def can_evict(s: ServiceState) -> bool:
        # K8s can only evict while the service has restart budget remaining.
        # Once max_restarts is exhausted, the cluster stops scheduling the pod (operator alert).
        return s.status in {"healthy", "degraded"} and s.restarts < s.max_restarts

    return EnvironmentSpec[ServiceState](
        name="k8s",
        behaviors=[
            Action("k8s:evict-pod", can_evict, evict),
        ],
        guarantees={
            # K8s doesn't corrupt the restart counter (it only increments on eviction)
            "restarts-non-negative": lambda s: s.restarts >= 0,
        },
        assumptions={
            "node-capacity": Assumption(
                name="node-capacity",
                description="At least one schedulable node is always available after eviction",
                status="unverified",
                source="Kubernetes docs: Pod lifecycle",
            ),
            "eviction-rate-bounded": Assumption(
                name="eviction-rate-bounded",
                description="Eviction rate is bounded so max_restarts is not exceeded in practice",
                status="unverified",
                source="cluster SLA",
            ),
        },
    )


def main() -> int:
    print("Open-system model checking: distributed service vs K8s pod eviction\n")

    model = _service_model()

    # 1. Closed model: no environment. Always passes.
    closed = check(model)
    print(f"  Closed model (no faults):               {closed}")
    assert closed.ok

    # 2. Open model, fragile: eviction silently kills the service → availability invariant violated.
    fragile = check_open(model, _k8s_env(resilient=False))
    print(f"  Open model, fragile (vs k8s eviction):  {fragile.result}")
    assert not fragile.ok
    assert fragile.result.invariant == "always-responsive"

    # 3. Open model, resilient: eviction triggers a restart. Service recovers.
    resilient = check_open(model, _k8s_env(resilient=True))
    print(f"  Open model, resilient (vs k8s eviction): {resilient.result}")
    assert resilient.ok, str(resilient)

    # 4. Show residual proof obligations.
    print(f"\n  Residual proof obligations ({len(resilient.unverified_assumptions)} unverified):")
    for a in resilient.unverified_assumptions:
        print(f"    [{a.status}] {a.name}")
        print(f"             {a.description}")

    print(
        "\nKey insight: the same service model fails under K8s eviction without restart logic.\n"
        "check_open explores EVERY possible eviction timing (the BFS is adversarial), so\n"
        "the availability invariant is verified over all reachable states — not just tested."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
