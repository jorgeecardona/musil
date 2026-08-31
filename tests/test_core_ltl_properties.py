"""Metamorphic property tests for the core (check / explore / check_of) and LTL layers: relationships that
must hold on EVERY model, checked over many randomly generated small models (fixed seed, pure stdlib). These
complement the known-verdict corpus by exercising the soundness-critical paths broadly:

- ``check_of(explore(m), m)`` gives the SAME verdict as ``check(m)`` (independent traversal code).
- the general Büchi engine agrees with the proven reductions: ``F``/``G``/``GF`` forced through the engine
  (``true U p`` / ``false R p`` / ``G(true U p)``) equal their reducible forms, over random models AND random
  predicates -- the strongest guard on the engine (the riskiest LTL code), e.g. against a future native port.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from musil import (
    Action,
    Always,
    And,
    Atom,
    Eventually,
    GeneralizedBuchi,
    Model,
    Not,
    Release,
    Until,
    check,
    check_all,
    check_ltl,
    check_of,
    explore,
)


@dataclass(frozen=True)
class St:
    id: int


def _edge_action(src: int, dst: int, name: str) -> Action[St]:
    return Action(name, enabled=lambda s: s.id == src, apply=lambda s: St(dst))


def _not_id(bad: int) -> Callable[[St], bool]:
    return lambda s: s.id != bad


def _is_id(t: int) -> Callable[[St], bool]:
    return lambda s: s.id == t


def _in_ids(ids: frozenset[int]) -> Callable[[St], bool]:
    return lambda s: s.id in ids


def _random_model(rng: random.Random, n: int) -> Model[St]:
    """A random model over states 0..n-1: each state has 0-2 outgoing edges (0 -> a sink, exercising deadlock
    / stutter paths). Half get an invariant ``id != bad`` (so ``check`` sometimes reports a violation); a
    third declare a random state terminal (a legitimate sink), else no state is terminal (``id == -1`` never
    holds, so sinks are real deadlocks)."""
    actions: list[Action[St]] = []
    for src in range(n):
        for j in range(rng.randint(0, 2)):
            actions.append(_edge_action(src, rng.randrange(n), f"e{src}_{j}"))
    invariants = {"inv": _not_id(rng.randrange(n))} if rng.random() < 0.5 else {}
    terminal = _is_id(rng.randrange(n)) if rng.random() < 0.33 else _is_id(-1)  # _is_id(-1) = never terminal
    return Model(init=St(0), actions=actions, invariants=invariants, terminal=terminal)


def test_check_of_agrees_with_check_over_random_models() -> None:
    # check_of consumes a pre-built graph; check does its own early-exit BFS. Independent traversals must give
    # the identical verdict: ok, kind, and the broken invariant name.
    rng = random.Random(20)
    for _ in range(60):
        m = _random_model(rng, rng.randint(2, 5))
        r = check(m)
        r_of = check_of(explore(m), m)
        assert (r.ok, r.kind, r.invariant) == (r_of.ok, r_of.kind, r_of.invariant)


def test_check_agrees_with_check_all_over_random_models() -> None:
    # check early-exits at the first violation; check_all sweeps the whole space and BUCKETS the distinct
    # violations (distinct code from check). They must agree: check.ok iff check_all found nothing, and
    # check's reported (kind, invariant) is among check_all's results (check_all finds at least what check does).
    rng = random.Random(22)
    for _ in range(60):
        m = _random_model(rng, rng.randint(2, 5))
        r = check(m)
        all_r = check_all(m)
        assert r.ok == (all_r == [])
        if not r.ok:
            assert any((v.kind, v.invariant) == (r.kind, r.invariant) for v in all_r)


def test_ltl_engine_agrees_with_reductions_over_random_models() -> None:
    # F/G/GF forced through the general Büchi engine must equal their reducible forms, over random models and
    # random state predicates. A disagreement is a soundness bug in the engine.
    rng = random.Random(21)
    true_atom = Atom[St]("true", lambda _s: True)
    never = Atom[St]("false", lambda _s: False)
    for _ in range(40):
        n = rng.randint(2, 4)
        m = _random_model(rng, n)
        for _ in range(3):
            a = Atom[St]("p", _in_ids(frozenset(i for i in range(n) if rng.random() < 0.5)))
            assert check_ltl(m, Until(true_atom, a)).ok == check_ltl(m, Eventually(a)).ok  # F
            assert check_ltl(m, Release(never, a)).ok == check_ltl(m, Always(a)).ok  # G
            assert check_ltl(m, Always(Until(true_atom, a))).ok == check_ltl(m, Always(Eventually(a))).ok  # GF


def test_degeneralize_preserves_has_accepting_run_over_random_models() -> None:
    # degeneralize() (generalized Büchi -> single-set Büchi, the counter construction) must not change the
    # ω-language: on every random model and formula, and for the formula AND its negation, the single-set
    # automaton's emptiness verdict equals the generalized one's. The riskiest new automata code, so guard it
    # broadly -- it will underpin the deterministic (LDBA) engine for quantitative LTL.
    rng = random.Random(23)
    for _ in range(40):
        n = rng.randint(2, 4)
        m = _random_model(rng, n)
        g = explore(m)
        for _ in range(3):
            a = Atom[St]("p", _in_ids(frozenset(i for i in range(n) if rng.random() < 0.5)))
            b = Atom[St]("q", _in_ids(frozenset(i for i in range(n) if rng.random() < 0.5)))
            forms = (Eventually(a), Until(a, b), Always(Eventually(a)),
                     And(Eventually(a), Eventually(b)), And(Always(Eventually(a)), Always(Eventually(b))))
            for phi in forms:
                for f in (phi, Not(phi)):
                    gba = GeneralizedBuchi[St].from_ltl(f)
                    assert gba.degeneralize().has_accepting_run(g) == gba.has_accepting_run(g)
