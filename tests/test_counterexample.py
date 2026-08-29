"""``minimize`` — delta-debug a violating trace down to the minimal failing action subsequence."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, Model, Result, Step, check, minimize


@dataclass(frozen=True)
class C:
    n: int


def _model() -> Model[C]:
    return Model(
        init=C(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 5, apply=lambda s: dc_replace(s, n=s.n + 1)),
            Action("noop", enabled=lambda s: True, apply=lambda s: s),  # irrelevant self-loop
        ],
        invariants={"n_le_2": lambda s: s.n <= 2},
        terminal=lambda s: False,
    )


def test_strips_irrelevant_actions_from_a_non_minimal_trace():
    m = _model()
    # A trace as a simulation or hand-assembled sequence might produce it: noop is irrelevant to n>2.
    padded = Result(
        ok=False,
        states_explored=0,
        kind="invariant",
        invariant="n_le_2",
        trace=(
            Step("<init>", C(0)),
            Step("noop", C(0)),
            Step("inc", C(1)),
            Step("noop", C(1)),
            Step("inc", C(2)),
            Step("inc", C(3)),
        ),
    )
    r = minimize(m, padded)
    assert [st.action for st in r.trace] == ["<init>", "inc", "inc", "inc"]
    assert r.trace[-1].state == C(3)
    assert r.invariant == "n_le_2"
    assert not r.ok


def test_a_bfs_counterexample_is_already_minimal():
    m = _model()
    original = check(m)  # BFS-shortest: inc, inc, inc
    assert not original.ok
    minimized = minimize(m, original)
    assert [st.action for st in minimized.trace] == [st.action for st in original.trace]


def test_ok_and_deadlock_results_pass_through_unchanged():
    ok_model = Model(init=C(0), actions=[Action("stay", lambda s: False, lambda s: s)], terminal=lambda s: True)
    ok = check(ok_model)
    assert minimize(ok_model, ok) is ok

    dead_model = Model(init=C(0), actions=[Action("noop", lambda s: False, lambda s: s)])
    dead = check(dead_model)
    assert dead.kind == "deadlock"
    assert minimize(dead_model, dead) is dead


def test_recomputes_reason_at_the_minimized_final_state():
    def rule(s: C) -> bool | str:
        return f"n is {s.n}" if s.n > 2 else True

    m = Model(
        init=C(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 5, apply=lambda s: dc_replace(s, n=s.n + 1)),
            Action("noop", enabled=lambda s: True, apply=lambda s: s),
        ],
        invariants={"bounded": rule},
        terminal=lambda s: False,
    )
    padded = Result(
        ok=False, states_explored=0, kind="invariant", invariant="bounded",
        trace=(Step("<init>", C(0)), Step("noop", C(0)), Step("inc", C(1)), Step("inc", C(2)), Step("inc", C(3))),
    )
    r = minimize(m, padded)
    assert [st.action for st in r.trace] == ["<init>", "inc", "inc", "inc"]
    assert r.reason == "n is 3"
