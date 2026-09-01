"""Gambler's ruin — the canonical absorbing random walk, three exact closed forms.

A gambler starts with `i` chips and bets one chip at a time on a coin, stopping at ruin (0 chips) or at the
goal `N`. This is the textbook DTMC: a 1-D random walk between two absorbing barriers. `musil.probabilistic`
returns each classical answer exactly, as `fractions.Fraction`:

- `reach_probability` on the FAIR walk — the probability of reaching `N` before `0` from start `i` is exactly
  `i / N`. (A martingale result: position is a fair game, so the win probability is linear in the stake.)
- `expected_reward` with a cost of 1 per step — the expected NUMBER OF BETS until the game ends (ruin or goal)
  is exactly `i * (N - i)`. A stochastic-shortest-path answer: every strategyless step costs 1, and the walk
  is absorbed almost surely, so the expectation is finite.
- `reach_probability(..., weight=...)` on a BIASED walk — when the up-step has probability `p` and the down
  `q = 1 - p`, the goal probability is `(1 - (q/p)^i) / (1 - (q/p)^N)`. Weights encode `p : q` as integers.

Everything is exact rational arithmetic: no sampling, no floating point, no dependency.

Run: python examples/gamblers_ruin.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction

from musil import Action, Model
from musil.probabilistic import assert_probability, expected_reward, reach_probability


@dataclass(frozen=True)
class Walk:
    pos: int  # chips in hand; the walk is absorbed at 0 (ruin) and at N (goal)


def walk_model(start: int, n: int, *, up: int = 1, down: int = 1) -> Model[Walk]:
    """The walk from `start` chips toward goal `n`. `up : down` are the (integer) relative weights of a
    winning vs losing bet; the default 1 : 1 is the fair coin. The two barriers (0 and n) are terminal."""
    return Model(
        init=Walk(start),
        actions=[
            Action("up", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos + 1)),
            Action("down", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos - 1)),
        ],
        terminal=lambda s: s.pos in (0, n),
    )


def _goal(n: int) -> Callable[[Walk], bool]:
    return lambda s: s.pos == n


def _absorbed(n: int) -> Callable[[Walk], bool]:
    return lambda s: s.pos in (0, n)


def _one_per_step(_name: str, _s: Walk) -> int:
    return 1  # every bet costs 1, so the expected reward is the expected number of bets


if __name__ == "__main__":
    N = 5

    print("Fair walk — P(reach N before 0) = i / N:")
    for i in range(N + 1):
        p = reach_probability(walk_model(i, N), _goal(N))
        print(f"  start {i}: {p}")
        assert_probability(p, equals=Fraction(i, N), label=f"P(goal | start {i})")

    print("\nFair walk — E[number of bets until absorbed] = i * (N - i):")
    for i in range(N + 1):
        dur = expected_reward(walk_model(i, N), _absorbed(N), cost=_one_per_step)
        print(f"  start {i}: {dur}")
        assert dur == Fraction(i * (N - i))

    print("\nBiased walk — up-step weighted 2 : 1 (p = 2/3), start 2 of 5:")
    # Closed form (1 - (q/p)^i) / (1 - (q/p)^N) with q/p = 1/2, i = 2, N = 5:
    #   (1 - 1/4) / (1 - 1/32) = (3/4) / (31/32) = 24/31.
    biased = reach_probability(walk_model(2, N, up=2, down=1), _goal(N), weight=lambda name, _s: 2 if name == "up" else 1)
    print(f"  P(reach goal) = {biased}")
    assert_probability(biased, equals=Fraction(24, 31), label="P(goal | biased, start 2)")

    print("\nAll three classical closed forms match exactly — no sampling, no floating point.")
