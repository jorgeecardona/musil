"""The distributed-systems kit: convergence (liveness) and fault tolerance (safety), from the builders.

Two shapes dominate infrastructure models, and musil builds both instead of hand-rolling them:

1. **A controller that converges.** `reconciler` gives the `converged` predicate and a fair reconcile
   action; the goal is `[]<>converged` ("always eventually reconciled"). Convergence holds *because* the
   reconcile is fair (the "ours" side of the fair-ours / unfair-faults discipline) — even as unfair faults
   keep knocking the system off target. Drop the fairness and a fault can starve reconcile forever, so the
   property fails: fairness is exactly what carries convergence.

2. **A cluster that tolerates faults.** `crash_actions` builds the crash/revive edges under a budget that
   bounds SIMULTANEOUS failures; a safety `check` proves the quorum invariant survives up to the budget and
   is broken past it.

Run: python examples/distributed_kit.py
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, replace

from musil import Action, Model, check, check_liveness, crash_actions, reconciler

# --- 1. a controller converging under faults --------------------------------------------------------


@dataclass(frozen=True)
class Ctrl:
    desired: str  # what the environment wants
    actual: str  # what the controller has achieved


def _desired(s: Ctrl) -> str:
    return s.desired


def _actual(s: Ctrl) -> str:
    return s.actual


def _set_actual(s: Ctrl, v: str) -> Ctrl:
    return replace(s, actual=v)


converged, reconcile = reconciler(get_desired=_desired, get_actual=_actual, set_actual=_set_actual)

CONTROLLER = Model(
    init=Ctrl("a", "a"),
    actions=[
        reconcile,  # fair="weak": while actual != desired, set actual to desired
        Action("flip", enabled=lambda s: True, apply=lambda s: replace(s, desired="b" if s.desired == "a" else "a")),
        Action("glitch", enabled=lambda s: True, apply=lambda s: replace(s, actual="stale")),  # an unfair fault
    ],
    terminal=lambda s: False,
)


# --- 2. a cluster keeping quorum through crashes ----------------------------------------------------


@dataclass(frozen=True)
class Cluster:
    up: frozenset[int]  # which of the 3 nodes are currently up


def _node_up(s: Cluster, n: Hashable) -> bool:
    return n in s.up


def _set_node_up(s: Cluster, n: Hashable, alive: bool) -> Cluster:
    assert isinstance(n, int)
    return Cluster(up=(s.up | {n}) if alive else (s.up - {n}))


def cluster(budget: int) -> Model[Cluster]:
    return Model(
        init=Cluster(frozenset(range(3))),
        actions=crash_actions(range(3), get_up=_node_up, set_up=_set_node_up, budget=budget, revive=True),
        invariants={"quorum": lambda s: len(s.up) >= 2},  # a majority stays up
        terminal=lambda s: False,
    )


if __name__ == "__main__":
    live = check_liveness(CONTROLLER, goal=converged, everywhere=True)
    print(f"[]<>converged, reconcile weak-fair : {'OK ' if live.ok else 'BAD'} (converges despite the fault)")
    unfair = check_liveness(CONTROLLER, goal=converged, everywhere=True, fair=())
    print(f"[]<>converged, no fairness          : {'OK ' if unfair.ok else 'BAD'} (a fault can starve reconcile)")

    ok1 = check(cluster(1))
    print(f"quorum holds with <=1 crash         : {'OK ' if ok1.ok else 'BAD'}")
    bad2 = check(cluster(2))
    print(f"quorum holds with <=2 crashes       : {'OK ' if bad2.ok else 'BAD'} (2 down -> only 1 up)")

    assert live.ok  # fair reconcile carries convergence...
    assert not unfair.ok  # ...and without it, the glitch fault can loop forever
    assert ok1.ok  # a budget of 1 keeps a majority up
    assert not bad2.ok and bad2.invariant == "quorum"  # a budget of 2 breaks quorum
    print("\nConvergence needs the reconcile to be fair; quorum needs the crash budget below N/2.")
