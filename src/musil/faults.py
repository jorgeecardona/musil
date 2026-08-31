"""Fault-injection action factories for the EXPLICIT-STATE path (``check`` / ``explore`` / ``check_open``).

``sim`` has a rich fault vocabulary (``Crash``, ``Partition``, ``FaultSchedule``), but it is reachable only
from the discrete-event ``Simulator``. Models written for the explicit-state checker hand-roll the same
crash / revive edges over and over. This kit builds those edges over a caller-declared projection of the
state — the same lens style as ``channels`` (``get`` / ``put``) — so a distributed model gets its standard
faults from one call instead of a per-node copy-paste.

Domain-free: nodes are any hashable ids, and the caller says how liveness is stored via ``get_up`` /
``set_up``. Splice the result into the model's ``actions`` alongside the protocol's own steps.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from musil.core import Action


def crash_actions[S: Hashable](
    nodes: Iterable[Hashable],
    *,
    get_up: Callable[[S, Hashable], bool],
    set_up: Callable[[S, Hashable, bool], S],
    budget: int | None = None,
    revive: bool = False,
    name: str = "fault",
) -> list[Action[S]]:
    """Crash (and optionally revive) actions over a caller-declared node-liveness projection.

    ``get_up(state, node) -> bool`` reads whether ``node`` is up; ``set_up(state, node, up) -> S`` returns
    the state with ``node``'s liveness set (a lens the caller owns — ``set_up`` then ``get_up`` must
    round-trip). One ``{name}:crash:{node}`` action per node fires when the node is up and fewer than
    ``budget`` nodes are already DOWN — so ``budget`` bounds the number of SIMULTANEOUS failures (``None`` =
    unbounded; with no ``revive`` a crash is permanent, so it also bounds the total). ``revive=True`` adds a
    ``{name}:revive:{node}`` action that brings a down node back up (for heal-able faults / VOPR-style
    liveness: after the faults clear, the system must reconverge).

    Returns a list of ``Action`` to splice into the model's ``actions``. Keep the fault actions UNFAIR (do
    not tag them ``fair=``, and do not name them in ``fair`` / ``fair_strong``) so a liveness proof cannot
    lean on a fault being scheduled."""
    node_list = list(nodes)

    def down_count(s: S) -> int:
        return sum(1 for n in node_list if not get_up(s, n))

    actions: list[Action[S]] = []
    for node in node_list:
        actions.append(
            Action(
                name=f"{name}:crash:{node}",
                enabled=lambda s, node=node: get_up(s, node) and (budget is None or down_count(s) < budget),
                apply=lambda s, node=node: set_up(s, node, False),
            )
        )
        if revive:
            actions.append(
                Action(
                    name=f"{name}:revive:{node}",
                    enabled=lambda s, node=node: not get_up(s, node),
                    apply=lambda s, node=node: set_up(s, node, True),
                )
            )
    return actions
