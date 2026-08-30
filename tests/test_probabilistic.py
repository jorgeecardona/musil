"""Exact DTMC reachability probability — checked against answers known from theory, not from musil.

The fair symmetric random walk (gambler's ruin) on 0..N has a closed form: the probability of reaching N
before 0 from position i is exactly i/N. The biased walk with up:down weight ratio has the closed form
(1-r^i)/(1-r^N) with r = down/up. Both are computed here by ``reach_probability`` over ``Fraction`` and
compared to the theory value, so this tests correctness, not merely "unchanged"."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pytest

from musil import Action, Model, reach_probability


@dataclass(frozen=True)
class Walk:
    pos: int


def walk_model(start: int, n: int) -> Model[Walk]:
    """Random walk on 0..n; 0 and n are absorbing (no action enabled there). n is the target ("win"),
    0 the loss. Interior states can step up or down."""
    return Model(
        init=Walk(start),
        actions=[
            Action("up", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos + 1)),
            Action("down", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos - 1)),
        ],
        terminal=lambda s: s.pos in (0, n),
    )


def _won(n: int):
    def target(s: Walk) -> bool:
        return s.pos == n

    return target


def test_fair_walk_matches_i_over_n():
    # Gambler's ruin, fair game: P(reach N before 0 | start i) = i/N, exactly.
    n = 4
    assert reach_probability(walk_model(1, n), _won(n)) == Fraction(1, 4)
    assert reach_probability(walk_model(2, n), _won(n)) == Fraction(1, 2)
    assert reach_probability(walk_model(3, n), _won(n)) == Fraction(3, 4)


def test_target_initial_is_one_and_unreachable_is_zero():
    n = 4
    assert reach_probability(walk_model(n, n), _won(n)) == Fraction(1)  # start already at target
    assert reach_probability(walk_model(0, n), _won(n)) == Fraction(0)  # start already lost, absorbing


def test_biased_weight_changes_the_exact_answer():
    # Same 3-state chain 0-1-2, start at 1. Uniform: up and down each 1/2 -> P(reach 2) = 1/2.
    # Weighted up:down = 2:1 -> P(reach 2) = 2/3 directly (up gets 2/3 of the mass out of state 1).
    n = 2

    def biased(name: str, _s: Walk) -> int:
        return 2 if name == "up" else 1

    assert reach_probability(walk_model(1, n), _won(n)) == Fraction(1, 2)
    assert reach_probability(walk_model(1, n), _won(n), weight=biased) == Fraction(2, 3)


def test_larger_fair_walk_exercises_the_linear_solve():
    # N=10 start=3 -> 3/10; a genuine 9-unknown I-P system solved exactly over the rationals.
    n = 10
    assert reach_probability(walk_model(3, n), _won(n)) == Fraction(3, 10)
    assert reach_probability(walk_model(7, n), _won(n)) == Fraction(7, 10)


def test_truncation_raises():
    # Unbounded upward walk (no ceiling): exploration truncates, so the probability is inconclusive.
    model = Model(
        init=Walk(0),
        actions=[Action("up", enabled=lambda s: True, apply=lambda s: Walk(s.pos + 1))],
        terminal=lambda s: False,
    )
    with pytest.raises(ValueError, match="truncated"):
        reach_probability(model, _won(5), max_states=50)
