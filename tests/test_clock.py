"""Bounded clock: timeouts in the explicit-state layer without an unbounded state space."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from musil import Action, BoundedClock, Model, bounded_clock, check, explore


@dataclass(frozen=True)
class World:
    now: int = 0
    replied: bool = False


def _clock(horizon: int) -> BoundedClock[World]:
    return bounded_clock(
        get=lambda s: s.now, put=lambda s, t: replace(s, now=t), horizon=horizon
    )


@dataclass(frozen=True)
class Req:
    now: int = 0
    replied_at: int | None = None


def _reply_by(deadline: int, horizon: int) -> tuple[Model[Req], BoundedClock[Req]]:
    """A request that may be answered at any tick, and a deadline it is meant to beat. The reply
    guard reads the clock -- exactly the shape this helper is meant to support. ``replied_at`` records
    *when*, so the invariant stays true once time moves on (an invariant over ``now`` alone would go
    false the tick after a perfectly punctual reply)."""
    clock: BoundedClock[Req] = bounded_clock(
        get=lambda s: s.now, put=lambda s, t: replace(s, now=t), horizon=horizon
    )
    model = Model(
        init=Req(),
        actions=[
            clock.action,
            Action(
                "reply",
                lambda s: s.replied_at is None and s.now <= deadline,
                lambda s: replace(s, replied_at=s.now),
            ),
        ],
        terminal=clock.at_horizon,
        invariants={"answered-in-time": lambda s: s.replied_at is None or s.replied_at <= deadline},
    )
    return model, clock


def test_the_clock_bounds_the_space_where_an_unbounded_one_only_looks_green() -> None:
    # an unbounded tick: check hits the cap and returns ok=True with truncated=True, which reads as
    # success. This is the failure mode bounded_clock exists to remove.
    runaway = Model(init=World(), actions=[Action("tick", lambda _s: True, lambda s: replace(s, now=s.now + 1))])
    loose = check(runaway, max_states=500)
    assert loose.ok and loose.truncated  # "OK", having proved nothing

    clock = _clock(8)
    bounded = Model(init=World(), actions=[clock.action], terminal=clock.at_horizon)
    tight = check(bounded)
    assert tight.ok and not tight.truncated


@pytest.mark.parametrize("horizon", [0, 1, 5, 20])
def test_state_count_is_linear_in_the_horizon(horizon: int) -> None:
    clock = _clock(horizon)
    model = Model(init=World(), actions=[clock.action], terminal=clock.at_horizon)
    graph = explore(model)
    assert len(graph.states) == horizon + 1


def test_a_binding_horizon_weakens_a_green_result() -> None:
    # deadline 2, horizon 2: the clock stops at the bound, so reachable states sit there. check is
    # green, but what was proved is "no violation within 2 ticks", not "no violation" -- and
    # binding() is what tells the reader which of the two they have.
    model, clock = _reply_by(deadline=2, horizon=2)
    graph = explore(model)
    assert check(model).ok
    assert clock.binding(graph)
    assert all(s.now == 2 for s in clock.horizon_states(graph))


def test_raising_the_horizon_does_not_help_a_model_that_can_always_tick() -> None:
    # the honest answer, and the reason binding() is worth reporting rather than assuming away: this
    # model never runs out of moves, so every horizon is reached. No number makes the claim stronger;
    # only changing the model (letting the reply stop the clock) does.
    for horizon in (2, 10, 50):
        model, clock = _reply_by(deadline=2, horizon=horizon)
        assert check(model).ok
        assert clock.binding(explore(model))


def test_a_model_that_finishes_before_the_bound_reports_a_non_binding_horizon() -> None:
    # the clock only ticks while unanswered, so a reply stops time: with horizon 9 the system runs
    # out of moves at tick 3, never reaching the bound.
    clock = _clock(9)
    model = Model(
        init=World(),
        actions=[
            Action("tick", lambda s: not s.replied and s.now < 3, lambda s: replace(s, now=s.now + 1)),
            Action("reply", lambda s: not s.replied and s.now == 3, lambda s: replace(s, replied=True)),
        ],
        terminal=lambda s: s.replied,
    )
    graph = explore(model)
    assert not clock.binding(graph)  # nothing ever reached tick 9


def test_forgetting_terminal_fails_loudly_at_the_horizon() -> None:
    # the tick is disabled at the bound, so a state whose only move was the tick has none left. That
    # is reported as a deadlock -- a false alarm, but a loud one whose trace ends at the horizon.
    clock = _clock(3)
    model = Model(init=World(), actions=[clock.action])  # no terminal=clock.at_horizon
    result = check(model)
    assert not result.ok
    assert result.kind == "deadlock"
    assert result.trace[-1].state.now == clock.horizon


def test_a_zero_horizon_clock_never_ticks() -> None:
    clock = _clock(0)
    model = Model(init=World(), actions=[clock.action], terminal=clock.at_horizon)
    graph = explore(model)
    assert graph.states == (World(now=0),)
    assert clock.at_horizon(World(now=0))


def test_a_negative_horizon_is_rejected() -> None:
    with pytest.raises(ValueError, match="horizon must be >= 0"):
        _clock(-1)


def test_the_action_name_is_prefixable() -> None:
    clock: BoundedClock[World] = bounded_clock(
        get=lambda s: s.now, put=lambda s, t: replace(s, now=t), horizon=2, name="gateway"
    )
    assert clock.action.name == "gateway:tick"
