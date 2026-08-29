"""``check_inductive`` — prove an invariant by k-induction over a finite domain, with
counterexamples-to-induction."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from musil import Action, InductionResult, Model, check_inductive


@dataclass(frozen=True)
class C:
    n: int


DOMAIN = [C(n) for n in range(5)]  # the FULL bounded state space, incl. unreachable states


def _add2_model(init: int = 0) -> Model[C]:
    # add2 fires while n+2 <= 4, so reachable from 0 is {0, 2, 4}; 1 and 3 are unreachable but in DOMAIN.
    return Model(
        init=C(init),
        actions=[Action("add2", enabled=lambda s: s.n + 2 <= 4, apply=lambda s: C(s.n + 2))],
        terminal=lambda s: True,
    )


def test_proven_for_a_1_inductive_invariant():
    m = _add2_model()
    r = check_inductive(m, lambda s: s.n <= 4, DOMAIN, k=1)
    assert isinstance(r, InductionResult)
    assert r.proven
    assert r.ok


def test_step_counterexample_from_an_unreachable_state():
    # n != 3 holds on the reachable set {0,2,4}, but is NOT 1-inductive: the unreachable state n=1
    # (which satisfies I) steps to n=3, which violates it. That is the whole value over `check`.
    r = check_inductive(_add2_model(), lambda s: s.n != 3, DOMAIN, k=1)
    assert not r.proven
    assert r.failure == "step"
    assert r.state == C(1)
    assert r.action == "add2"
    assert r.successor == C(3)


def test_k_induction_proves_what_1_induction_could_not():
    # The same n != 3 IS 2-inductive: any path of length 2 whose first two states satisfy I never lands
    # on n=3 (the only way into 3 is from 1, and 1->3 already breaks the length-2 antecedent).
    def inv(s: C) -> bool:
        return s.n != 3

    assert not check_inductive(_add2_model(), inv, DOMAIN, k=1).proven
    assert check_inductive(_add2_model(), inv, DOMAIN, k=2).proven


def test_base_case_catches_an_initial_violation():
    r = check_inductive(_add2_model(init=3), lambda s: s.n != 3, DOMAIN, k=1)
    assert not r.proven
    assert r.failure == "base"
    assert r.state == C(3)


def test_string_reason_is_carried_into_the_counterexample():
    def inv(s: C) -> bool | str:
        return "n reached 3" if s.n == 3 else True

    r = check_inductive(_add2_model(), inv, DOMAIN, k=1)
    assert not r.proven
    assert r.reason == "n reached 3"
    assert "n reached 3" in str(r)


def test_reachable_only_domain_proves_nothing_new():
    # 1-induction over ONLY the reachable states is trivially true for a passing model — the reason the
    # domain must include unreachable states. Here {0,2,4} never exposes the n=1 -> n=3 counterexample.
    reachable = [C(0), C(2), C(4)]
    assert check_inductive(_add2_model(), lambda s: s.n != 3, reachable, k=1).proven


def test_k_must_be_positive():
    with pytest.raises(ValueError, match="k must be"):
        check_inductive(_add2_model(), lambda s: True, DOMAIN, k=0)
