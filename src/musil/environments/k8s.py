"""Kubernetes platform fault environments.

EnvironmentSpec factory and AdversarialNode for K8s pod eviction and OOM kills.

Model checking::

    from dataclasses import replace
    from musil.environments.k8s import pod_eviction
    from musil.env import check_open
    env = pod_eviction(
        can_evict=lambda s: s.status == "running",
        on_evict=lambda s: replace(s, status="evicted"),
    )
    result = check_open(model, env)
    for a in result.unverified_assumptions:
        print(f"[{a.status}] {a.name}: {a.description}")

Simulation::

    from musil.environments.k8s import eviction_notifier
    nodes = {"app": MyApp(), "k8s": eviction_notifier()}
    report = simulate(lambda: nodes, seeds=range(100), ...)
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action
from musil.env import Assumption, EnvironmentSpec
from musil.sim import AdversarialNode, Context

# ---------------------------------------------------------------------------
# Assumptions (cite Kubernetes documentation)
# ---------------------------------------------------------------------------

NODE_CAPACITY = Assumption(
    name="k8s:node-capacity",
    description=(
        "At least one schedulable node exists after any eviction; "
        "the scheduler can always place the evicted pod"
    ),
    status="unverified",
    source="Kubernetes docs: Concepts > Workloads > Pod lifecycle § Disruptions",
)

SCHEDULER_LIVENESS = Assumption(
    name="k8s:scheduler-liveness",
    description="kube-scheduler eventually places any Pending pod on an available node",
    status="unverified",
    source="Kubernetes docs: Concepts > Scheduling, Preemption and Eviction",
)

EVICTION_RATE_BOUNDED = Assumption(
    name="k8s:eviction-rate-bounded",
    description=(
        "Concurrent pod evictions are bounded by the cluster PodDisruptionBudget; "
        "the scheduler will not evict pods beyond the budget"
    ),
    status="unverified",
    source="Kubernetes docs: Tasks > Run Applications > Configure a Disruption Budget",
)


# ---------------------------------------------------------------------------
# EnvironmentSpec factories
# ---------------------------------------------------------------------------

def pod_eviction[S: Hashable](
    *,
    can_evict: Callable[[S], bool],
    on_evict: Callable[[S], S],
    can_oom_kill: Callable[[S], bool] | None = None,
    on_oom_kill: Callable[[S], S] | None = None,
    extra_assumptions: dict[str, Assumption] | None = None,
) -> EnvironmentSpec[S]:
    """EnvironmentSpec for K8s pod eviction and optional OOM kills.

    Behaviors added:
    - ``k8s:evict-pod``: scheduler evicts the pod (guard: ``can_evict``, effect: ``on_evict``)
    - ``k8s:oom-kill``: OOM killer terminates the pod (optional; requires both ``can_oom_kill``
      and ``on_oom_kill``)

    Pre-wired assumptions: ``NODE_CAPACITY``, ``SCHEDULER_LIVENESS``, ``EVICTION_RATE_BOUNDED``.
    Pass ``extra_assumptions`` to add cluster-specific obligations.
    """
    behaviors: list[Action[S]] = [Action("k8s:evict-pod", can_evict, on_evict)]
    if can_oom_kill is not None and on_oom_kill is not None:
        behaviors.append(Action("k8s:oom-kill", can_oom_kill, on_oom_kill))

    assumptions: dict[str, Assumption] = {
        NODE_CAPACITY.name: NODE_CAPACITY,
        SCHEDULER_LIVENESS.name: SCHEDULER_LIVENESS,
        EVICTION_RATE_BOUNDED.name: EVICTION_RATE_BOUNDED,
    }
    if extra_assumptions:
        assumptions.update(extra_assumptions)

    return EnvironmentSpec[S](name="k8s", behaviors=behaviors, assumptions=assumptions)


# ---------------------------------------------------------------------------
# AdversarialNode factories
# ---------------------------------------------------------------------------

def eviction_notifier(*, msg: object = "k8s:evict") -> AdversarialNode:
    """AdversarialNode that sends a K8s eviction notification to any node that contacts it.

    Place this node in the simulation under a name like ``"k8s"``; any node that sends it a
    message receives an eviction notice in response.
    """
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(msg))])


def oom_notifier(*, msg: object = "k8s:oom-kill") -> AdversarialNode:
    """AdversarialNode that sends a K8s OOM kill notification to any node that contacts it."""
    def guard(_src: str, _payload: object) -> bool:
        return True

    def _make_response(m: object) -> Callable[[Context, str, object], None]:
        def response(ctx: Context, src: str, _payload: object) -> None:
            ctx.send(src, m)
        return response

    return AdversarialNode(behaviors=[(guard, _make_response(msg))])
