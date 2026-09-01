"""GPVW construction (GeneralizedBuchi.from_ltl): validated by DIFFERENTIAL testing against the trusted
reducible-fragment reductions, plus hand-verified Until/Next cases. Not yet wired into check_ltl."""

from __future__ import annotations

from dataclasses import dataclass

from musil import (
    LTL,
    Action,
    Always,
    And,
    Atom,
    Eventually,
    Implies,
    Model,
    Next,
    Not,
    Until,
    check_ltl,
    explore,
)
from musil.ltl import GeneralizedBuchi


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


GREEN = Atom[Light]("green", lambda s: s.color == "green")
RED = Atom[Light]("red", lambda s: s.color == "red")
YELLOW = Atom[Light]("yellow", lambda s: s.color == "yellow")
KNOWN = Atom[Light]("known", lambda s: s.color in {"red", "green", "yellow"})
TRUE = Atom[Light]("true", lambda s: True)


def _holds(model: Model[Light], phi: LTL[Light]) -> bool:
    """model |= phi, via the GPVW engine: build the automaton for Not(phi); phi holds iff it has no
    accepting run (no counterexample)."""
    return not GeneralizedBuchi[Light].from_ltl(Not(phi)).has_accepting_run(explore(model))


def test_gpvw_agrees_with_the_reducible_fragment():
    m = _light()
    cases: list[LTL[Light]] = [
        Always(KNOWN),  # True
        Always(RED),  # False (green reachable)
        Eventually(GREEN),  # True
        Always(Eventually(RED)),  # True (recurrence)
        Always(Implies(YELLOW, Eventually(RED))),  # True (response)
        Not(Eventually(GREEN)),  # False (G !green)
        Not(Always(GREEN)),  # True (F !green)
        And(Always(KNOWN), Always(Eventually(RED))),  # True
        And(Always(KNOWN), Always(RED)),  # False
    ]
    for phi in cases:
        assert _holds(m, phi) == check_ltl(m, phi).ok, f"GPVW disagrees with the reduction on {phi}"


def test_until_matches_eventually_when_left_is_true():
    # (true U green) is exactly F green — cross-check GPVW's Until against the trusted F reduction
    m = _light()
    assert _holds(m, Until(TRUE, GREEN)) == check_ltl(m, Eventually(GREEN)).ok
    assert _holds(m, Until(TRUE, GREEN))  # F green holds on the light


def test_next_operator():
    m = _light()
    assert _holds(m, Next(GREEN))  # from red, step 1 is green -> X green holds
    assert not _holds(m, Next(RED))  # from red, step 1 is green, not red -> X red fails


def test_next_nested_in_global_implication():
    m = _light()
    # G(yellow -> X red): yellow's only successor is red, so this holds.
    assert _holds(m, Always(Implies(YELLOW, Next(RED))))
    # G(green -> X red): green goes to yellow, not red, so this fails.
    assert not _holds(m, Always(Implies(GREEN, Next(RED))))


def test_real_until_true_and_false_cases():
    # On the cycling light (all runs infinite, no terminal-state stutter needed):
    m = _light()
    # green U yellow: from the initial state red, green is false and yellow not yet reached, so the
    # "until" is violated immediately -> FALSE.
    assert not _holds(m, Until(GREEN, YELLOW))
    # (red | green | yellow) U green == known U green: known holds at red, then green is reached -> TRUE.
    assert _holds(m, Until(KNOWN, GREEN))
