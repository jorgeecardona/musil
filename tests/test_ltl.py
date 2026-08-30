"""LTL formula AST + check_ltl (the fragment reducible to check/check_liveness)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from musil import (
    Action,
    Always,
    And,
    Atom,
    Buchi,
    Eventually,
    GeneralizedBuchi,
    Implies,
    Model,
    Next,
    Not,
    Or,
    Result,
    Until,
    check_ltl,
    explore,
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
    # a conjunction with a general-engine conjunct still works: both hold (yellow U red holds from red)
    assert check_ltl(m, And(Always(_KNOWN), Until(_YELLOW, _RED))).ok


def test_buchi_product_emptiness_detects_the_accepting_cycle():
    # Buchi for ¬(G green) = F(¬green): reach a non-green state and loop. Non-green IS reachable, so an
    # accepting cycle exists -> the product is non-empty -> G green is FALSE on the light.
    g = explore(_light())
    f_not_green = Buchi[Light](
        initial=frozenset({0}),
        accepting=frozenset({1}),
        transitions={
            0: ((lambda s: True, 0), (lambda s: s.color != "green", 1)),
            1: ((lambda s: True, 1),),
        },
    )
    assert f_not_green.has_accepting_run(g)  # G green is violated


def test_buchi_product_emptiness_reports_none_when_the_bad_state_is_unreachable():
    # Buchi for ¬(G known) = F(¬known): a non-known color is NEVER reachable, so no accepting run ->
    # the product is empty -> G known-color HOLDS.
    g = explore(_light())
    f_not_known = Buchi[Light](
        initial=frozenset({0}),
        accepting=frozenset({1}),
        transitions={
            0: ((lambda s: True, 0), (lambda s: s.color not in {"red", "green", "yellow"}, 1)),
            1: ((lambda s: True, 1),),
        },
    )
    assert not f_not_known.has_accepting_run(g)  # G known-color holds


def test_buchi_product_blocks_a_run_the_guard_forbids():
    # Buchi for ¬(F green) = G(¬green): stay only while non-green. The light forces green every cycle, so
    # no infinite non-green run exists -> no accepting cycle -> F green HOLDS (every run reaches green).
    g = explore(_light())
    g_not_green = Buchi[Light](
        initial=frozenset({0}),
        accepting=frozenset({0}),
        transitions={0: ((lambda s: s.color != "green", 0),)},
    )
    assert not g_not_green.has_accepting_run(g)  # F green holds


def test_generalized_buchi_requires_every_acceptance_set():
    g = explore(_light())
    # automaton alternates q0 <-> q1 each step; two acceptance sets {0} and {1}. The product is one big
    # reachable cycle visiting both q0 and q1 infinitely -> intersects every set -> accepting.
    alternate: dict[int, tuple[tuple[Callable[[Light], bool], int], ...]] = {
        0: ((lambda s: True, 1),),
        1: ((lambda s: True, 0),),
    }
    gba_ok = GeneralizedBuchi[Light](
        initial=frozenset({0}), accepting_sets=(frozenset({0}), frozenset({1})), transitions=alternate
    )
    assert gba_ok.has_accepting_run(g)
    # add a third acceptance set {2} that no automaton state is in -> no SCC can intersect it -> rejected.
    gba_bad = GeneralizedBuchi[Light](
        initial=frozenset({0}),
        accepting_sets=(frozenset({0}), frozenset({1}), frozenset({2})),
        transitions=alternate,
    )
    assert not gba_bad.has_accepting_run(g)
    # no acceptance sets at all -> any non-trivial reachable SCC accepts (unconstrained infinite run)
    gba_empty = GeneralizedBuchi[Light](initial=frozenset({0}), accepting_sets=(), transitions=alternate)
    assert gba_empty.has_accepting_run(g)


def test_general_engine_handles_the_previously_refused_fragment():
    m = _light()
    # yellow U red: from the initial state red, red already holds -> the until is satisfied -> holds.
    assert check_ltl(m, Until(_YELLOW, _RED)).ok
    # X green: from red, step 1 is green -> holds.
    assert check_ltl(m, Next(_GREEN)).ok
    # X red: from red, step 1 is green, not red -> fails.
    assert not check_ltl(m, Next(_RED)).ok
    # a bare state formula is evaluated at time 0: the init is red, not green -> green fails at time 0.
    assert not check_ltl(m, _GREEN).ok
    assert check_ltl(m, _RED).ok  # the init IS red


def test_engine_returns_a_counterexample_lasso():
    m = _light()
    r = check_ltl(m, Next(_RED))  # X red fails: from red, step 1 is green (engine path -> a Result)
    assert isinstance(r, Result)
    assert not r.ok
    assert r.kind == "ltl"
    assert r.trace[0].action == "<init>"
    assert r.trace[0].state == Light("red")  # the counterexample starts at the initial state
    assert r.trace[1].state == Light("green")  # step 1 is green, witnessing X red is false
    # a holding formula yields no counterexample (empty trace)
    ok = check_ltl(m, Next(_GREEN))
    assert isinstance(ok, Result)
    assert ok.ok
    assert ok.trace == ()


def test_general_engine_stutters_terminal_states():
    @dataclass(frozen=True)
    class N:
        n: int

    line = Model(
        init=N(0),
        actions=[Action("step", enabled=lambda s: s.n < 2, apply=lambda s: N(s.n + 1))],
        terminal=lambda s: s.n == 2,
    )
    at1 = Atom[N]("at1", lambda s: s.n == 1)
    at2 = Atom[N]("at2", lambda s: s.n == 2)
    # X at1 holds (step 1 is n=1); X at2 fails (step 1 is n=1). n=2 is terminal, so without the stutter
    # self-loop the single run 0->1->2 would be finite and the Büchi product would see no run at all.
    assert check_ltl(line, Next(at1)).ok
    assert not check_ltl(line, Next(at2)).ok
