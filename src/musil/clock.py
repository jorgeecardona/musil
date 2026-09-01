"""A bounded discrete clock for the explicit-state layer -- timeouts without an unbounded space.

``sim`` has a virtual clock; ``Model``/``Action`` has none, so every timeout model (a wait with a
deadline, a retry ladder that gives up) hand-rolls the same two things: a tick action, and a bound to
stop it running forever. The bound is the part that is easy to get wrong, and getting it wrong is
quiet. An unbounded clock does not fail -- ``check`` hits ``max_states`` and returns
``Result(ok=True, truncated=True)``, which reads as success to ``if result:`` and prints as
``OK -- 1000000 states, no violations (TRUNCATED at cap)``. Nothing was proved and it looks like
something was.

``bounded_clock`` makes the bound a declared number instead of an open-coded guard, and makes the
question it raises answerable: **was the horizon binding?** A green result under a binding horizon
means "no violation within ``horizon`` ticks", which is a weaker claim than "no violation" and should
not be quoted as the stronger one.

Domain-free, like the rest of the kit: the clock lives in a field of the caller's own state, read by
``get`` and written by ``put``.

    clock = bounded_clock(get=lambda s: s.now, put=lambda s, t: replace(s, now=t), horizon=8)
    model = Model(
        init=World(),
        actions=[*my_actions, clock.action],
        invariants={...},
        terminal=clock.at_horizon,   # see below -- running out of time is a legitimate sink
    )
    graph = explore(model)
    assert not clock.binding(graph)   # or say so when reporting the result

``terminal`` matters: at the horizon the tick is disabled, so a state whose only remaining move was
the tick has no enabled action and ``check`` calls it a deadlock. That is a false alarm -- the model
did not deadlock, time ran out -- so mark those states terminal (``terminal=clock.at_horizon``, or
``lambda s: clock.at_horizon(s) or mine(s)``). Forgetting it fails loudly, with a trace ending at the
horizon, which is the failure mode to prefer over a silent one."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from musil.core import Action, Graph

__all__ = [
    "BoundedClock",
    "bounded_clock",
]


@dataclass(frozen=True, slots=True)
class BoundedClock[S: Hashable]:
    """A clock that advances one tick at a time and stops at ``horizon``. Built by ``bounded_clock``.

    ``action`` is the tick, to be added to the model's actions. ``now`` reads the clock out of a
    state, ``at_horizon`` says whether a state sits at the bound, and ``binding`` answers the
    question the bound raises."""

    horizon: int
    action: Action[S]
    now: Callable[[S], int]
    at_horizon: Callable[[S], bool]

    def horizon_states(self, graph: Graph[S]) -> tuple[S, ...]:
        """The reachable states sitting at the horizon -- where exploration stopped because the
        clock was not allowed to advance, not because the system had nowhere left to go."""
        return tuple(s for s in graph.states if self.at_horizon(s))

    def binding(self, graph: Graph[S]) -> bool:
        """Did the horizon cut the exploration? False means the model finished on its own with time
        to spare, so the bound cost nothing and a green result is a result about the whole model.
        True means the bound was reached, and a green result only says "no violation within
        ``horizon`` ticks" -- raise the horizon until this goes False, or quote the weaker claim."""
        return bool(self.horizon_states(graph))


def bounded_clock[S: Hashable](
    *,
    get: Callable[[S], int],
    put: Callable[[S, int], S],
    horizon: int,
    name: str = "clock",
) -> BoundedClock[S]:
    """A tick action over the caller's clock field, bounded at ``horizon``.

    ``get(state)`` reads the current tick and ``put(state, t)`` returns a state with the clock at
    ``t``. The action is named ``f"{name}:tick"`` and is enabled exactly while ``get(state) <
    horizon``, so the clock contributes at most ``horizon + 1`` values to the state space -- linear
    in the horizon, and finite by construction rather than by hitting ``max_states``.

    ``horizon`` must be non-negative. ``horizon=0`` is a clock that never ticks, which is a valid
    (if pointless) model rather than an error -- the value is then always the initial one.

    Deadlines are ordinary guards over ``get``: a timeout fires when ``get(s) >= armed_at + delay``,
    a retry is enabled while ``get(s) < give_up_at``. This helper does not model those, it only
    supplies the time they are read from and the bound that keeps them finite."""
    if horizon < 0:
        raise ValueError(f"horizon must be >= 0, got {horizon}")

    def at_horizon(state: S) -> bool:
        return get(state) >= horizon

    return BoundedClock(
        horizon=horizon,
        action=Action(
            name=f"{name}:tick",
            enabled=lambda s: get(s) < horizon,
            apply=lambda s: put(s, get(s) + 1),
        ),
        now=get,
        at_horizon=at_horizon,
    )
