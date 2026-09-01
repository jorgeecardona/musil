"""``invariant_coverage`` — which invariants are load-bearing vs candidate-vacuous (the dual of
``coverage``, which is about actions)."""

from __future__ import annotations

from dataclasses import dataclass

from musil import Action, Model, check, explore
from musil.metrics import InvariantCoverage, invariant_coverage, invariant_coverage_of


@dataclass(frozen=True)
class S:
    n: int


def _model() -> Model[S]:
    # inc is guarded off at n==3; applying it there gives n=4, which violates n_le_3 → load-bearing.
    # No action ever drives n negative, so n_nonneg is threatened by nothing → candidate-vacuous.
    return Model(
        init=S(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 3, apply=lambda s: S(s.n + 1)),
            Action("reset", enabled=lambda s: True, apply=lambda s: S(0)),
        ],
        invariants={"n_le_3": lambda s: s.n <= 3, "n_nonneg": lambda s: s.n >= 0},
        terminal=lambda s: False,
    )


def test_distinguishes_load_bearing_from_candidate_vacuous():
    m = _model()
    assert check(m).ok  # a passing model: the point is that green says nothing about which invariant works
    ic = invariant_coverage(m)
    assert isinstance(ic, InvariantCoverage)
    assert ic.load_bearing == ("n_le_3",)
    assert ic.candidate_vacuous == ("n_nonneg",)
    assert ic.threats["n_le_3"] == ("inc",)
    assert ic.ok is False  # something is candidate-vacuous


def test_invariant_coverage_of_matches_the_explore_wrapper():
    m = _model()
    assert invariant_coverage_of(explore(m), m) == invariant_coverage(m)


def test_str_names_the_vacuous_and_the_guard():
    s = str(invariant_coverage(_model()))
    assert "candidate-vacuous" in s
    assert "n_nonneg" in s
    assert "n_le_3: guarded off by inc" in s


@dataclass(frozen=True)
class Q:
    items: tuple[int, ...]


def test_partial_apply_that_relies_on_its_guard_is_skipped_not_crashed():
    # `head`'s apply reads items[0]; guarded off on the empty queue, where items[0] raises. The analysis
    # applies guarded-off actions, so it must swallow that rather than crash.
    m: Model[Q] = Model(
        init=Q(()),
        actions=[
            Action("push", enabled=lambda q: len(q.items) < 2, apply=lambda q: Q((*q.items, len(q.items)))),
            Action("head", enabled=lambda q: len(q.items) > 0, apply=lambda q: Q((q.items[0],))),
        ],
        invariants={"bounded": lambda q: len(q.items) <= 2},
        terminal=lambda q: False,
    )
    ic = invariant_coverage(m)  # must not raise despite head's partial apply
    assert ic.load_bearing == ("bounded",)  # push, guarded off at len==2, would overflow it
    assert ic.threats["bounded"] == ("push",)


def test_all_load_bearing_reports_ok():
    m = Model(
        init=S(0),
        actions=[Action("inc", enabled=lambda s: s.n < 3, apply=lambda s: S(s.n + 1))],
        invariants={"n_le_3": lambda s: s.n <= 3},
        terminal=lambda s: s.n == 3,
    )
    ic = invariant_coverage(m)
    assert ic.ok is True
    assert ic.candidate_vacuous == ()
