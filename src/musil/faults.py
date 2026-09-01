"""Fault-injection action factories for the EXPLICIT-STATE path (``check`` / ``explore`` / ``check_open``).

``sim`` has a rich fault vocabulary (``Crash``, ``Partition``, ``FaultSchedule``), but it is reachable only
from the discrete-event ``Simulator``. Models written for the explicit-state checker hand-roll the same
crash / revive / partition / heal edges over and over. This kit builds those edges over a caller-declared
projection of the state — the same lens style as ``channels`` (``get`` / ``put``) — so a distributed model
gets its standard faults from one call instead of a per-node copy-paste: ``crash_actions`` for node
liveness, ``partition_actions`` for network reachability.

Domain-free: nodes are any hashable ids, and the caller says how liveness is stored via ``get_up`` /
``set_up``. Splice the result into the model's ``actions`` alongside the protocol's own steps.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from musil.core import Action

__all__ = [
    "crash_actions",
    "partition_actions",
]


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


def partition_actions[S: Hashable](
    splits: Iterable[Hashable],
    *,
    get_reach: Callable[[S], Hashable],
    set_reach: Callable[[S, Hashable], S],
    healed: Hashable,
    name: str = "fault",
) -> list[Action[S]]:
    """Partition (and heal) actions over a caller-declared reachability field.

    The model stores a reachability CONFIGURATION somewhere in its state — whatever shape the caller uses (a
    per-node reachable-set map, a partition of the nodes into groups, a split label...). ``get_reach(state)``
    reads it; ``set_reach(state, reach) -> S`` returns the state with it set (a lens the caller owns).
    ``healed`` is the full-reachability configuration (typically the model's initial one; it must compare
    equal via ``==`` to the healed state's field).

    For each configuration in ``splits`` a ``{name}:partition:{i}`` action installs it — enabled only while
    currently HEALED, so partitions do not stack — and a single ``{name}:heal`` action restores ``healed``
    from any partitioned configuration. This is the heal-able network-partition fault: the system runs
    partitioned, then the partition clears and it must reconverge. Keep these actions UNFAIR (do not tag them
    or name them in ``fair`` / ``fair_strong``), like ``crash_actions``, so a liveness proof cannot lean on a
    partition healing on its own."""
    configs = list(splits)
    actions: list[Action[S]] = [
        Action(
            name=f"{name}:partition:{i}",
            enabled=lambda s: get_reach(s) == healed,
            apply=lambda s, split=split: set_reach(s, split),
        )
        for i, split in enumerate(configs)
    ]
    if configs:
        actions.append(
            Action(
                name=f"{name}:heal",
                enabled=lambda s: get_reach(s) != healed,
                apply=lambda s: set_reach(s, healed),
            )
        )
    return actions
