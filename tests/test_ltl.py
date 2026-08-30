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


def test_out_of_fragment_refuses_rather_than_guessing():
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), Until(_YELLOW, _RED))
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), Next(_GREEN))
    with pytest.raises(NotImplementedError, match="outside the fragment"):
        check_ltl(_light(), _GREEN)  # a bare state formula: wrap it in Always/Eventually
