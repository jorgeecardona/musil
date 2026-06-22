"""Liveness checking: eventually-P, P-unreachable, fair cycles, and weak fairness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from musil import Action, Model, check_liveness


@dataclass(frozen=True)
class N:
    v: int = 0
    done: bool = False


def test_eventually_reached_on_every_run() -> None:
    # 0 -> 1 -> 2(done); P = done. Every run reaches it.
    model = Model(
        init=N(),
        actions=[
            Action("step", lambda s: s.v < 2, lambda s: replace(s, v=s.v + 1)),
            Action("finish", lambda s: s.v == 2 and not s.done, lambda s: replace(s, done=True)),
        ],
        terminal=lambda s: s.done,
    )
    assert check_liveness(model, goal=lambda s: s.done, goal_name="done").ok


def test_p_unreachable_is_detected() -> None:
    # a branch that wanders into a sink from which 'done' can never be reached
    @dataclass(frozen=True)
    class M:
        at: str = "start"

    model = Model(
        init=M(),
        actions=[
            Action("win", lambda s: s.at == "start", lambda s: replace(s, at="done")),
            Action("trap", lambda s: s.at == "start", lambda s: replace(s, at="trap")),
        ],
        terminal=lambda s: s.at in {"done", "trap"},
    )
    result = check_liveness(model, goal=lambda s: s.at == "done", goal_name="done")
    assert not result.ok
    assert result.kind == "p-unreachable"
    assert result.stem[-1].state == M("trap")


def test_fair_cycle_violates_without_fairness_but_holds_with_it() -> None:
    # a toggle A<->B (never 'P'), with an 'escape' action enabled in BOTH states leading to P.
    @dataclass(frozen=True)
    class T:
        at: str = "A"

    model = Model(
        init=T(),
        actions=[
            Action("a2b", lambda s: s.at == "A", lambda s: replace(s, at="B")),
            Action("b2a", lambda s: s.at == "B", lambda s: replace(s, at="A")),
            # escape is enabled in both A and B -> continuously enabled on the A<->B cycle
            Action("escape", lambda s: s.at in {"A", "B"}, lambda s: replace(s, at="P")),
        ],
        terminal=lambda s: s.at == "P",
    )
    goal: Callable[[T], bool] = lambda s: s.at == "P"  # noqa: E731

    # no fairness: the A<->B loop that ignores escape is a valid counterexample
    strict = check_liveness(model, goal=goal, goal_name="P")
    assert not strict.ok
    assert strict.kind == "fair-cycle"
    assert len(strict.cycle) >= 1

    # weak fairness on 'escape' (continuously enabled on the loop) -> the loop is inadmissible -> holds
    fair = check_liveness(model, goal=goal, goal_name="P", fair=["escape"])
    assert fair.ok, str(fair)


def test_weak_fairness_does_not_force_a_flickering_action() -> None:
    # escape enabled only in A (not continuously enabled on A<->B) -> weak fairness can't force it
    @dataclass(frozen=True)
    class T:
        at: str = "A"

    model = Model(
        init=T(),
        actions=[
            Action("a2b", lambda s: s.at == "A", lambda s: replace(s, at="B")),
            Action("b2a", lambda s: s.at == "B", lambda s: replace(s, at="A")),
            Action("escape", lambda s: s.at == "A", lambda s: replace(s, at="P")),  # only in A
        ],
        terminal=lambda s: s.at == "P",
    )
    goal: Callable[[T], bool] = lambda s: s.at == "P"  # noqa: E731
    # even with weak fairness on escape, the flicker (disabled in B) means the loop is admissible
    result = check_liveness(model, goal=goal, goal_name="P", fair=["escape"])
    assert not result.ok
    assert result.kind == "fair-cycle"


def test_strong_fairness_forces_a_flickering_action_that_weak_cannot() -> None:
    # escape enabled only in A of an A<->B cycle (so enabled infinitely often, but not continuously)
    @dataclass(frozen=True)
    class T:
        at: str = "A"

    model = Model(
        init=T(),
        actions=[
            Action("a2b", lambda s: s.at == "A", lambda s: replace(s, at="B")),
            Action("b2a", lambda s: s.at == "B", lambda s: replace(s, at="A")),
            Action("escape", lambda s: s.at == "A", lambda s: replace(s, at="P")),  # only in A
        ],
        terminal=lambda s: s.at == "P",
    )
    goal: Callable[[T], bool] = lambda s: s.at == "P"  # noqa: E731
    # weak fairness can't force escape (not continuously enabled) -> still a counterexample
    assert not check_liveness(model, goal=goal, fair=["escape"]).ok
    # strong fairness CAN (escape is enabled infinitely often) -> liveness holds
    assert check_liveness(model, goal=goal, fair_strong=["escape"]).ok


def test_goal_true_at_init_is_trivially_live() -> None:
    model = Model(init=N(v=0, done=True), actions=[])
    assert check_liveness(model, goal=lambda s: s.done).ok


def test_everywhere_recurrence_vs_eventually_from_init() -> None:
    # starts satisfying P, but can drift into a ¬P sink-cycle. <>P from init is trivially true;
    # []<>P (everywhere) must catch the reachable stale cycle.
    @dataclass(frozen=True)
    class W:
        at: str = "ok"  # "ok" satisfies P; "stuck" loops forever in ¬P

    model = Model(
        init=W(),
        actions=[
            Action("drift", lambda s: s.at == "ok", lambda s: replace(s, at="stuck")),
            Action("spin", lambda s: s.at == "stuck", lambda s: s),  # ¬P self-loop
        ],
    )
    goal: Callable[[W], bool] = lambda s: s.at == "ok"  # noqa: E731
    assert check_liveness(model, goal=goal).ok  # <>P: holds at init
    recurrence = check_liveness(model, goal=goal, everywhere=True)  # []<>P: reachable stale cycle
    assert not recurrence.ok
    assert recurrence.stem[-1].state == W("stuck")
