"""LTL formula AST + check_ltl (the fragment reducible to check/check_liveness)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from musil import (
    Action,
    Always,
    And,
    Atom,
    Eventually,
    Implies,
    Model,
    Next,
    Not,
    Or,
    Until,
    check_ltl,
)


@dataclass(frozen=True)
class Light:
    color: str


def _light() -> Model[Light]:
    return Model(
        init=Light("red"),
        actions=[
            Action("go", enabled=lambda s: s.color == "red", apply=lambda s: Light("green")),
            Action("slow", enabled=lambda s: s.color == "green", apply=lambda s: Light("yellow")),
            Action("stop", enabled=lambda s: s.color == "yellow", apply=lambda s: Light("red")),
        ],
    )


def _atom(name: str, pred: Callable[[Light], bool]) -> Atom[Light]:
    return Atom(name, pred)


_GREEN = _atom("green", lambda s: s.color == "green")
_RED = _atom("red", lambda s: s.color == "red")
_YELLOW = _atom("yellow", lambda s: s.color == "yellow")
_KNOWN = _atom("known", lambda s: s.color in {"red", "green", "yellow"})


def test_formula_str_rendering():
    assert str(Always(Eventually(_GREEN))) == "G F green"
    assert str(Implies(_YELLOW, Eventually(_RED))) == "(yellow -> F red)"
    assert str(Not(_GREEN)) == "!green"


def test_safety_always_state_is_an_invariant():
    assert check_ltl(_light(), Always(_KNOWN)).ok  # G known-color holds
    assert not check_ltl(_light(), Always(_RED)).ok  # G red fails (green is reachable)


def test_eventually_state():
    assert check_ltl(_light(), Eventually(_GREEN)).ok  # <> green on every run


def test_recurrence_gf():
    assert check_ltl(_light(), Always(Eventually(_RED))).ok  # []<> red


def test_response_g_implies_f():
    assert check_ltl(_light(), Always(Implies(_YELLOW, Eventually(_RED)))).ok  # yellow ~> red


def test_boolean_combination_in_a_state_formula():
    # G (known-color & !blue) and G (green | !green) are still pure state formulas -> safety invariants
    not_blue = _atom("not-blue", lambda s: s.color != "blue")
    assert check_ltl(_light(), Always(And(_KNOWN, not_blue))).ok
    assert check_ltl(_light(), Always(Or(_GREEN, Not(_GREEN)))).ok  # tautology holds everywhere


def test_negated_temporal_forms_reduce_via_pushed_negation():
    m = _light()
    # !F green == G !green : fails, green is reachable
    assert not check_ltl(m, Not(Eventually(_GREEN))).ok
    # !G green == F !green : holds, a non-green state is reachable
    assert check_ltl(m, Not(Always(_GREEN))).ok
    # !G known == F !known : fails, every reachable state has a known color
    assert not check_ltl(m, Not(Always(_KNOWN))).ok
    # double negation collapses: !!G known == G known : holds
    assert check_ltl(m, Not(Not(Always(_KNOWN)))).ok


def test_pushed_negation_preserves_the_response_shape():
    # G(yellow -> F red) must still match the response reduction after negation-pushing (Implies kept)
    assert check_ltl(_light(), Always(Implies(_YELLOW, Eventually(_RED)))).ok


def test_conjunction_splits_into_independent_checks():
    m = _light()
    # G known-color  &  []<> red  : both hold
    assert check_ltl(m, And(Always(_KNOWN), Always(Eventually(_RED)))).ok
    # G known-color  &  G red : the second conjunct fails, and its failing result is returned
    r = check_ltl(m, And(Always(_KNOWN), Always(_RED)))
    assert not r.ok
    # a conjunction with an irreducible conjunct propagates the refusal
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(m, And(Always(_KNOWN), Until(_YELLOW, _RED)))


def test_out_of_fragment_refuses_rather_than_guessing():
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), Until(_YELLOW, _RED))
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), Next(_GREEN))
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), _GREEN)  # a bare state formula: wrap it in Always/Eventually
