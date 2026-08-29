"""``minimize`` — delta-debug a violating trace down to the minimal failing action subsequence."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace

import pytest

from musil import (
    Action,
    Model,
    Result,
    Step,
    as_regression_test,
    check,
    minimize,
    replay_actions,
)


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


def test_replay_actions_reports_the_violation_along_a_named_sequence():
    m = _model()
    r = replay_actions(m, ["inc", "inc", "inc"])
    assert not r.ok
    assert r.invariant == "n_le_2"
    assert r.trace[-1].state == C(3)


def test_replay_actions_ok_when_the_sequence_stays_valid():
    m = _model()
    assert replay_actions(m, ["inc", "inc"]).ok  # reaches n=2, still within n<=2


def test_replay_actions_raises_on_a_stale_sequence():
    m = Model(init=C(0), actions=[Action("inc", lambda s: s.n < 1, lambda s: dc_replace(s, n=s.n + 1))])
    with pytest.raises(ValueError, match="does not replay"):
        replay_actions(m, ["inc", "inc"])  # second inc is disabled at n=1


def test_as_regression_test_emits_a_runnable_minimal_replay():
    m = _model()
    padded = Result(
        ok=False, states_explored=0, kind="invariant", invariant="n_le_2",
        trace=(Step("<init>", C(0)), Step("noop", C(0)), Step("inc", C(1)), Step("inc", C(2)), Step("inc", C(3))),
    )
    src = as_regression_test(m, padded, test_name="n_overflow", model_import="from mymod import model")
    # the emitted sequence is minimized (noop dropped)
    assert "['inc', 'inc', 'inc']" in src
    assert "def test_n_overflow():" in src
    assert "from mymod import model" in src
    assert "replay_actions(model," in src
    assert "assert not result.ok" in src
    assert "assert result.invariant == 'n_le_2'" in src

    # and the emitted body actually reproduces the violation when run against the model
    namespace: dict[str, object] = {"model": m}
    exec(src.replace("from mymod import model", "pass"), namespace)  # exercise the generated source
    generated = namespace["test_n_overflow"]
    assert callable(generated)
    generated()  # must not raise


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
