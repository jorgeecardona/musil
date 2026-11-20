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


# --- leads-to / response: [](Q -> <>P) --------------------------------------------------------


@dataclass(frozen=True)
class Phase:
    at: str = "I"


def _phase_model(actions_spec: dict[str, set[str]]) -> Model[Phase]:
    acts: list[Action[Phase]] = [
        Action(f"{a}->{b}", lambda s, _a=a: s.at == _a, lambda s, _b=b: replace(s, at=_b))
        for a, bs in actions_spec.items()
        for b in bs
    ]
    return Model(init=Phase(), actions=acts, terminal=lambda s: not actions_spec.get(s.at))


def test_leadsto_holds_when_trigger_always_reaches_goal() -> None:
    # I->T->G->G ; whenever at T (Q), eventually at G (P). From T the only move reaches G.
    model = _phase_model({"I": {"T"}, "T": {"G"}, "G": {"G"}})
    r = check_liveness(model, goal=lambda s: s.at == "G", leadsto_from=lambda s: s.at == "T")
    assert r.ok


def test_leadsto_fails_when_trigger_can_avoid_goal_forever() -> None:
    # at T there's a self-loop that never reaches G — a fair cycle violating Q->[]<>... no fairness.
    model = _phase_model({"I": {"T"}, "T": {"T", "G"}, "G": {"G"}})
    r = check_liveness(model, goal=lambda s: s.at == "G", leadsto_from=lambda s: s.at == "T")
    assert not r.ok and r.kind == "fair-cycle"
    # weak fairness of the escape action repairs it (T->G continuously enabled along the T-loop)
    r2 = check_liveness(
        model, goal=lambda s: s.at == "G", leadsto_from=lambda s: s.at == "T", fair=["T->G"]
    )
    assert r2.ok


def test_leadsto_is_weaker_than_everywhere() -> None:
    # a ¬P cycle (L->L) that NO trigger reaches: everywhere=True fails, but leads-to holds because
    # the only Q-state (T) always reaches P (G). This is the soundness-distinguishing case.
    model = _phase_model({"I": {"T", "L"}, "T": {"G"}, "G": {"G"}, "L": {"L"}})
    goal: Callable[[Phase], bool] = lambda s: s.at == "G"  # noqa: E731
    assert not check_liveness(model, goal=goal, everywhere=True).ok  # L loops, never P
    assert check_liveness(
        model, goal=goal, leadsto_from=lambda s: s.at == "T"
    ).ok  # T always reaches G


def test_leadsto_p_unreachable_when_trigger_reaches_a_dead_end() -> None:
    # I->T(trigger)->X(¬P sink) ; from T the goal G is never reachable → p-unreachable, not a cycle.
    model = _phase_model({"I": {"T", "G"}, "T": {"X"}, "X": set(), "G": {"G"}})
    r = check_liveness(model, goal=lambda s: s.at == "G", leadsto_from=lambda s: s.at == "T")
    assert not r.ok and r.kind == "p-unreachable"


def test_leadsto_from_overrides_everywhere_flag() -> None:
    # documented: when leadsto_from is given, `everywhere` is ignored. The L->L ¬P cycle would make
    # everywhere=True fail, but leadsto_from=T (which always reaches G) must still hold regardless.
    model = _phase_model({"I": {"T", "L"}, "T": {"G"}, "G": {"G"}, "L": {"L"}})
    r = check_liveness(
        model, goal=lambda s: s.at == "G", leadsto_from=lambda s: s.at == "T", everywhere=True
    )
    assert r.ok


def test_everywhere_is_always_eventually_not_reachability() -> None:
    # A loop that forever declines an available exit: enter/exit forever, with `finish` legal in
    # every state. The goal stays *reachable* from everywhere (reaches == all states), yet strict
    # []<>P is violated by the loop — `everywhere=True` means always *eventually*, not always
    # *reachable*. Naming the exit weakly fair discharges the loop; `reaches` answers the weaker
    # question directly.
    from musil import explore, reaches

    model = Model(
        init=N(),
        actions=[
            Action("enter", lambda s: s.v == 0 and not s.done, lambda s: replace(s, v=1)),
            Action("exit", lambda s: s.v == 1 and not s.done, lambda s: replace(s, v=0)),
            Action("finish", lambda s: not s.done, lambda s: replace(s, done=True)),
        ],
        terminal=lambda s: s.done,
    )
    g = explore(model)
    assert reaches(g, lambda s: s.done) == set(g.states)  # never trapped ...
    strict = check_liveness(model, goal=lambda s: s.done, everywhere=True, goal_name="done")
    assert not strict.ok and strict.kind == "fair-cycle"  # ... yet a run can loop forever
    assert check_liveness(model, goal=lambda s: s.done, everywhere=True, fair=["finish"]).ok


def test_strong_fairness_checks_a_cycle_inside_a_larger_scc() -> None:
    # {A, B, C} is one SCC and 'z' is enabled in C. The sub-cycle A <-> B never enables 'z',
    # so it is strongly fair and never reaches G (#45).
    def move(src: str, dst: str) -> Callable[[str], str]:
        return lambda _s: dst

    edges = [
        ("ab", "A", "B"),
        ("ba", "B", "A"),
        ("bc", "B", "C"),
        ("cb", "C", "B"),
        ("z", "C", "G"),
    ]
    actions = [Action(name, lambda s, a=src: s == a, move(src, dst)) for name, src, dst in edges]
    actions.append(Action("g", lambda s: s == "G", lambda _s: "G"))
    model = Model(init="A", actions=actions, invariants={})
    assert not check_liveness(model, goal=lambda s: s == "G", fair_strong=("z",)).ok
