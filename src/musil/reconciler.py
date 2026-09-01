"""The controller / reconciler shape as a builder — desired↔actual convergence under faults.

A ``desired`` field set by the environment, an ``actual`` field the controller drives toward it, a fair
reconcile step, unfair faults (loss, crash, concurrent reconcilers), and the goal ``[]<>converged``: this is
the single most common shape in modern infrastructure (operators, sync engines, cache maintainers), and it
is the one musil had no builder for (it has ``channels`` for messaging and ``fsm`` for state tables).

``reconciler`` produces the two pieces every such model writes by hand — the ``converged`` predicate and a
fair reconcile ``Action`` — and composes with the rest of the kit: attach ``faults.crash_actions`` /
``channels`` as UNFAIR actions or ``env`` environments, and check ``[]<>converged`` with
``check_liveness(everywhere=True)`` (or ``check_liveness_open`` against an adversarial environment). The
reconcile action is tagged ``fair="weak"`` — the "ours" side of the fair-ours / unfair-faults discipline: a
liveness proof may assume the controller keeps reconciling, but not that a fault heals on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable

from musil.core import Action

__all__ = [
    "reconciler",
]


def reconciler[S: Hashable, V](
    *,
    get_desired: Callable[[S], V],
    get_actual: Callable[[S], V],
    set_actual: Callable[[S, V], S],
    name: str = "reconcile",
) -> tuple[Callable[[S], bool], Action[S]]:
    """The canonical desired↔actual reconciler. ``get_desired`` / ``get_actual`` read the two fields (any
    hashable values); ``set_actual(state, value)`` returns the state with ``actual`` set. Returns
    ``(converged, reconcile)``:

    - ``converged(state)`` is ``get_actual(state) == get_desired(state)`` — the ``[]<>converged`` goal,
      typically fed to ``check_liveness(model, goal=converged, everywhere=True)``.
    - ``reconcile`` is a fair ``Action`` (tagged ``fair="weak"``) that, while not converged, sets ``actual``
      to ``desired`` in one step.

    Splice ``reconcile`` into the model's actions next to the environment's desired-changing steps and your
    UNFAIR faults (``crash_actions``, channel loss, extra reconcilers). For a controller that converges over
    several steps rather than one, build your own reconcile ``Action`` and use only ``converged`` from here."""

    def converged(state: S) -> bool:
        return get_actual(state) == get_desired(state)

    reconcile = Action(
        name=name,
        enabled=lambda s: not converged(s),
        apply=lambda s: set_actual(s, get_desired(s)),
        fair="weak",
    )
    return converged, reconcile
