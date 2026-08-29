"""check_all (exhaustive multi-violation check) + a regression that check() canonicalizes SUCCESSORS."""
from collections.abc import Callable
from dataclasses import dataclass

from musil import Action, Invariant, Model, check, check_all


@dataclass(frozen=True)
class Counter:
    n: int


def _always_terminal(_s: Counter) -> bool:
    return True


def _model(
    invariants: dict[str, Invariant[Counter]],
    *,
    hi: int = 3,
    terminal: Callable[[Counter], bool] = _always_terminal,
) -> Model[Counter]:
    return Model(
        init=Counter(0),
        actions=[Action("inc", lambda s: s.n < hi, lambda s: Counter(s.n + 1))],
        invariants=invariants,
        terminal=terminal,
    )


def test_check_all_returns_every_distinct_invariant_with_shortest_trace():
    # Two invariants break at different depths: at_most_1 fails first (n=2), at_most_2 later (n=3).
    m = _model({"at_most_1": lambda s: s.n <= 1, "at_most_2": lambda s: s.n <= 2})
    results = check_all(m)
    broken = {r.invariant for r in results}
    assert broken == {"at_most_1", "at_most_2"}
    # each carries a reproducible trace; ordered shortest-first
    assert all(r.trace for r in results)
    assert [len(r.trace) for r in results] == sorted(len(r.trace) for r in results)
    # the first-broken invariant has the shorter witness
    by_name = {r.invariant: r for r in results}
    assert len(by_name["at_most_1"].trace) < len(by_name["at_most_2"].trace)
    # check() stops at the FIRST (shortest) only
    first = check(m)
    assert not first.ok and first.invariant == "at_most_1"


def test_check_all_distinct_by_reason_separates_failure_modes():
    def rule(s: Counter):
        if s.n == 2:
            return "hit two"
        if s.n == 3:
            return "hit three"
        return True

    m = _model({"rule": rule})
    assert {r.invariant for r in check_all(m)} == {"rule"}  # one entry by name
    reasons = {r.reason for r in check_all(m, distinct_by="reason")}
    assert reasons == {"hit two", "hit three"}  # two entries by (invariant, reason)


def test_check_all_empty_when_model_is_correct():
    assert check_all(_model({"always": lambda s: True})) == []


def test_check_all_reports_deadlock():
    # a non-terminal dead end: inc disabled at n=1, and n=1 is not terminal
    m = Model(
        init=Counter(0),
        actions=[Action("inc", lambda s: s.n < 1, lambda s: Counter(s.n + 1))],
        invariants={"always": lambda s: True},
        terminal=lambda s: s.n == 0,
    )
    results = check_all(m)
    assert any(r.kind == "deadlock" for r in results)


def test_check_canonicalizes_successors():
    """Regression: check() must canonicalize SUCCESSOR states, not only the initial ones (it previously did
    `nxt = action.apply(state)` with no canon, so symmetry reduction was a silent no-op in check)."""

    @dataclass(frozen=True)
    class Pair:
        a: int
        b: int

    acts: list[Action[Pair]] = [
        Action("a", lambda s: s.a < 2, lambda s: Pair(s.a + 1, s.b)),
        Action("b", lambda s: s.b < 2, lambda s: Pair(s.a, s.b + 1)),
    ]
    inv: dict[str, Invariant[Pair]] = {"ok": lambda s: True}
    m = Model(init=Pair(0, 0), actions=acts, invariants=inv, terminal=lambda s: True)
    full = check(m)
    reduced = check(m, canonicalize=lambda s: Pair(*sorted((s.a, s.b))))
    assert reduced.states_explored < full.states_explored  # canon actually collapsed the symmetric half
