"""Metamorphic property tests for the probabilistic layer: invariants that must hold on EVERY DTMC/MDP,
checked over many randomly generated small models (fixed seed, exact rational -- no float tolerance). These
complement the known-verdict corpus: a known verdict pins one answer, these pin RELATIONSHIPS that catch whole
classes of bugs (a probability outside [0,1], a bounded value exceeding the unbounded one, a distribution not
summing to 1, min > max) -- the differential-oracle role, e.g. against a future native port. Pure stdlib."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from musil import (
    Action,
    Atom,
    Eventually,
    Model,
    long_run_probability,
    probability_ltl,
    reach_probability,
    reach_probability_mdp,
    transient_distribution,
)


@dataclass(frozen=True)
class St:
    id: int


def _edge(src: int, dst: int, name: str) -> Action[St]:
    return Action(name, enabled=lambda s: s.id == src, apply=lambda s: St(dst))


def _random_model(rng: random.Random, n: int) -> tuple[Model[St], Callable[[str, St], int], Callable[[St], bool]]:
    """A random DTMC/MDP over states 0..n-1: each state has 1-3 outgoing edges to random states with random
    integer weights 1-3 (so every state has a successor -- no deadlocks), and a random target subset."""
    actions: list[Action[St]] = []
    weights: dict[str, int] = {}
    for src in range(n):
        for j in range(rng.randint(1, 3)):
            name = f"e{src}_{j}"
            actions.append(_edge(src, rng.randrange(n), name))
            weights[name] = rng.randint(1, 3)
    model = Model(init=St(0), actions=actions, terminal=lambda s: False)
    target_ids = {i for i in range(n) if rng.random() < 0.4}

    def weight(name: str, _s: St) -> int:
        return weights[name]

    def target(s: St) -> bool:
        return s.id in target_ids

    return model, weight, target


def _singletons(_s: St, enabled: tuple[Action[St], ...]) -> list[Sequence[Action[St]]]:
    return [[a] for a in enabled]  # each action its own move: maximal nondeterminism


def test_reach_probability_bounded_is_monotone_and_below_unbounded() -> None:
    # reach_probability(steps=k) uses a finite backward induction (_bounded_values); the unbounded one uses the
    # linear solve (_dtmc_values). Independent code, so a strong cross-check: the bounded value is in [0,1],
    # non-decreasing in k, and never exceeds the unbounded probability.
    rng = random.Random(0)
    for _ in range(40):
        m, weight, target = _random_model(rng, rng.randint(2, 5))
        unbounded = reach_probability(m, target, weight=weight)
        assert Fraction(0) <= unbounded <= Fraction(1)
        prev = Fraction(0)
        for k in range(8):
            bk = reach_probability(m, target, weight=weight, steps=k)
            assert Fraction(0) <= bk <= unbounded  # in range, and bounded <= unbounded
            assert bk >= prev  # non-decreasing in k
            prev = bk


def test_transient_distribution_always_sums_to_one() -> None:
    rng = random.Random(1)
    for _ in range(40):
        m, weight, _ = _random_model(rng, rng.randint(2, 5))
        for k in range(6):
            pi = transient_distribution(m, k, weight=weight)
            assert sum(pi.values()) == Fraction(1)
            assert all(Fraction(0) <= v <= Fraction(1) for v in pi.values())


def test_mdp_max_is_at_least_min_and_bounds_the_dtmc() -> None:
    # Over all schedulers, max reachability >= min, both in [0,1]; and a uniform DTMC (one move over all
    # enabled actions) lies between them (it is one particular "scheduler").
    rng = random.Random(2)

    def one_move(_s: St, enabled: tuple[Action[St], ...]) -> list[Sequence[Action[St]]]:
        return [list(enabled)]

    for _ in range(30):
        m, weight, target = _random_model(rng, rng.randint(2, 4))
        mx = reach_probability_mdp(m, target, moves=_singletons, weight=weight, optimize="max")
        mn = reach_probability_mdp(m, target, moves=_singletons, weight=weight, optimize="min")
        dtmc = reach_probability_mdp(m, target, moves=one_move, weight=weight, optimize="max")  # = the DTMC
        assert Fraction(0) <= mn <= mx <= Fraction(1)
        assert mn <= dtmc <= mx


def test_long_run_probability_in_unit_interval() -> None:
    rng = random.Random(3)
    for _ in range(40):
        m, weight, target = _random_model(rng, rng.randint(2, 5))
        assert Fraction(0) <= long_run_probability(m, target, weight=weight) <= Fraction(1)


def test_probability_ltl_F_matches_reach_probability() -> None:
    # P(F target) via the LTL layer must equal the direct reachability probability -- pins the wiring.
    rng = random.Random(4)
    for _ in range(30):
        m, weight, target = _random_model(rng, rng.randint(2, 5))
        via_ltl = probability_ltl(m, Eventually(Atom[St]("t", target)), weight=weight)
        assert via_ltl == reach_probability(m, target, weight=weight)
