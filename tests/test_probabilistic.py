"""Exact DTMC reachability probability — checked against answers known from theory, not from musil.

The fair symmetric random walk (gambler's ruin) on 0..N has a closed form: the probability of reaching N
before 0 from position i is exactly i/N. The biased walk with up:down weight ratio has the closed form
(1-r^i)/(1-r^N) with r = down/up. Both are computed here by ``reach_probability`` over ``Fraction`` and
compared to the theory value, so this tests correctness, not merely "unchanged"."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction

import pytest

from musil import Action, Model, expected_reward, reach_probability, reach_probability_mdp


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


# --------------------------------------------------------------------------------------------------
# MDP: nondeterministic choice on top of the distributions, solved exactly by policy iteration.
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    tag: str  # "start", "win" (target), "dead" (absorbing loss)


def _win(s: Choice) -> bool:
    return s.tag == "win"


def two_gamble_model() -> Model[Choice]:
    """From ``start`` a scheduler chooses move A or move B; each is a coin over win/dead. With weights
    B_win:B_lose = 2:1 (others 1), move A wins with prob 1/2, move B with prob 2/3."""
    start, win, dead = Choice("start"), Choice("win"), Choice("dead")
    at_start: Callable[[Choice], bool] = lambda s: s.tag == "start"  # noqa: E731
    return Model(
        init=start,
        actions=[
            Action("A_win", enabled=at_start, apply=lambda s: win),
            Action("A_lose", enabled=at_start, apply=lambda s: dead),
            Action("B_win", enabled=at_start, apply=lambda s: win),
            Action("B_lose", enabled=at_start, apply=lambda s: dead),
        ],
        terminal=lambda s: s.tag in ("win", "dead"),
    )


def _by_leading_letter(_state: Choice, enabled: tuple[Action[Choice], ...]) -> list[Sequence[Action[Choice]]]:
    # Group actions by their first letter: {A_win, A_lose} is move A, {B_win, B_lose} is move B.
    groups: dict[str, list[Action[Choice]]] = {}
    for a in enabled:
        groups.setdefault(a.name[0], []).append(a)
    return list(groups.values())


def _singletons(_state: Choice, enabled: tuple[Action[Choice], ...]) -> list[Sequence[Action[Choice]]]:
    # Every enabled action is its own (Dirac) move -> pure nondeterministic choice, no probability mixing.
    return [[a] for a in enabled]


def test_mdp_max_and_min_pick_opposite_coins():
    m = two_gamble_model()

    def biased(name: str, _s: Choice) -> int:
        return 2 if name == "B_win" else 1

    # Uniform: A and B are both fair coins -> 1/2 either way. Weighted: A wins 1/2, B wins 2/3.
    assert reach_probability_mdp(m, _win, moves=_by_leading_letter) == Fraction(1, 2)
    assert reach_probability_mdp(m, _win, moves=_by_leading_letter, weight=biased) == Fraction(2, 3)  # max=B
    assert reach_probability_mdp(m, _win, moves=_by_leading_letter, weight=biased, optimize="min") == Fraction(1, 2)


def test_mdp_max_improves_off_a_bad_initial_policy():
    # start has two singleton moves: "stay" self-loops (value 0), "go" reaches the target (value 1).
    # The initial policy is the FIRST move (stay) -> V=0; max policy iteration must switch to go -> V=1.
    start, win = Choice("start"), Choice("win")
    at_start: Callable[[Choice], bool] = lambda s: s.tag == "start"  # noqa: E731
    m = Model(
        init=start,
        actions=[
            Action("stay", enabled=at_start, apply=lambda s: start),  # defined first => initial policy
            Action("go", enabled=at_start, apply=lambda s: win),
        ],
        terminal=lambda s: s.tag == "win",
    )
    assert reach_probability_mdp(m, _win, moves=_singletons) == Fraction(1)


def test_mdp_min_avoids_target_via_self_loop():
    # Same stay/go model: the MIN scheduler stays forever -> 0. This is the case that stalls naive min
    # policy iteration (the self-loop move keeps its current value); S0min pins it to 0.
    start, win = Choice("start"), Choice("win")
    at_start: Callable[[Choice], bool] = lambda s: s.tag == "start"  # noqa: E731
    m = Model(
        init=start,
        actions=[
            Action("stay", enabled=at_start, apply=lambda s: start),
            Action("go", enabled=at_start, apply=lambda s: win),
        ],
        terminal=lambda s: s.tag == "win",
    )
    assert reach_probability_mdp(m, _win, moves=_singletons, optimize="min") == Fraction(0)
    assert reach_probability_mdp(m, _win, moves=_singletons) == Fraction(1)  # max still escapes


def test_mdp_min_avoids_target_via_end_component():
    # u1 <-> u2 form a non-target END COMPONENT (each can loop to the other) and each can also escape to the
    # target. The min scheduler loops in the EC forever -> 0; S0min = {u1, u2} is what makes this exact.
    u1, u2, win = Choice("u1"), Choice("u2"), Choice("win")
    at1: Callable[[Choice], bool] = lambda s: s.tag == "u1"  # noqa: E731
    at2: Callable[[Choice], bool] = lambda s: s.tag == "u2"  # noqa: E731
    m = Model(
        init=u1,
        actions=[
            Action("u1_to_u2", enabled=at1, apply=lambda s: u2),
            Action("u1_esc", enabled=at1, apply=lambda s: win),
            Action("u2_to_u1", enabled=at2, apply=lambda s: u1),
            Action("u2_esc", enabled=at2, apply=lambda s: win),
        ],
        terminal=lambda s: s.tag == "win",
    )
    assert reach_probability_mdp(m, _win, moves=_singletons, optimize="min") == Fraction(0)
    assert reach_probability_mdp(m, _win, moves=_singletons) == Fraction(1)  # max escapes


def test_mdp_single_move_recovers_the_dtmc():
    # Grouping every enabled action into ONE move = no choice = the DTMC. Must match reach_probability.
    def one_move(_state: Walk, enabled: tuple[Action[Walk], ...]) -> list[Sequence[Action[Walk]]]:
        return [list(enabled)]

    for start in range(5):
        walk = walk_model(start, 4)
        assert reach_probability_mdp(walk, _won(4), moves=one_move) == reach_probability(walk, _won(4))


# --------------------------------------------------------------------------------------------------
# Step-bounded reachability: probability of reaching the target WITHIN k transitions (exact, finite).
# --------------------------------------------------------------------------------------------------


def coin_loop_model() -> Model[Choice]:
    # start: "win" -> target, "again" -> start; uniform so each is 1/2. P(reach within k) = 1 - (1/2)^k.
    start, win = Choice("start"), Choice("win")
    at_start: Callable[[Choice], bool] = lambda s: s.tag == "start"  # noqa: E731
    return Model(
        init=start,
        actions=[
            Action("win", enabled=at_start, apply=lambda s: win),
            Action("again", enabled=at_start, apply=lambda s: start),
        ],
        terminal=lambda s: s.tag == "win",
    )


def test_bounded_dtmc_is_one_minus_half_to_the_k():
    m = coin_loop_model()
    assert reach_probability(m, _win, steps=0) == Fraction(0)  # start is not the target
    assert reach_probability(m, _win, steps=1) == Fraction(1, 2)
    assert reach_probability(m, _win, steps=2) == Fraction(3, 4)
    assert reach_probability(m, _win, steps=3) == Fraction(7, 8)
    assert reach_probability(m, _win) == Fraction(1)  # unbounded: reaches almost surely


def test_bounded_negative_steps_raises():
    m = coin_loop_model()
    with pytest.raises(ValueError, match="non-negative"):
        reach_probability(m, _win, steps=-1)
    with pytest.raises(ValueError, match="non-negative"):
        reach_probability_mdp(m, _win, moves=_singletons, steps=-1)


def test_bounded_mdp_horizon_matters():
    # Deterministic chain s0 -> s1 -> win: reachable within 1 step is impossible (only s1); within 2, sure.
    s0, s1, win = Choice("s0"), Choice("s1"), Choice("win")
    at0: Callable[[Choice], bool] = lambda s: s.tag == "s0"  # noqa: E731
    at1: Callable[[Choice], bool] = lambda s: s.tag == "s1"  # noqa: E731
    m = Model(
        init=s0,
        actions=[
            Action("a", enabled=at0, apply=lambda s: s1),
            Action("b", enabled=at1, apply=lambda s: win),
        ],
        terminal=lambda s: s.tag == "win",
    )
    assert reach_probability_mdp(m, _win, moves=_singletons, steps=1) == Fraction(0)
    assert reach_probability_mdp(m, _win, moves=_singletons, steps=2) == Fraction(1)


def test_bounded_mdp_max_and_min_within_one_step():
    m = two_gamble_model()

    def biased(name: str, _s: Choice) -> int:
        return 2 if name == "B_win" else 1

    # The whole decision is one step, so a 1-step horizon already gives the unbounded max/min.
    assert reach_probability_mdp(m, _win, moves=_by_leading_letter, steps=0) == Fraction(0)
    assert reach_probability_mdp(m, _win, moves=_by_leading_letter, weight=biased, steps=1) == Fraction(2, 3)
    m_min = reach_probability_mdp(m, _win, moves=_by_leading_letter, weight=biased, steps=1, optimize="min")
    assert m_min == Fraction(1, 2)


# --------------------------------------------------------------------------------------------------
# Expected reward: expected accumulated cost (default: number of steps) to first reach the target.
# --------------------------------------------------------------------------------------------------


def test_expected_steps_is_the_geometric_mean():
    # Coin loop: win with prob 1/2 each step -> expected steps to win = 1/p = 2.
    assert expected_reward(coin_loop_model(), _win) == Fraction(2)


def test_expected_reward_scales_with_cost():
    # Same coin loop, but each step costs 3: expected total cost = 3 * expected steps = 6.
    def cost3(_name: str, _s: Choice) -> int:
        return 3

    assert expected_reward(coin_loop_model(), _win, cost=cost3) == Fraction(6)


def test_expected_steps_gamblers_ruin_absorption_time():
    # Symmetric walk on 0..N with BOTH ends absorbing (target = absorbed): expected time to absorption from
    # i is exactly i(N-i), a classic closed form. Reached almost surely, so the expectation is finite.
    n = 4

    def absorbed(s: Walk) -> bool:
        return s.pos in (0, n)

    for i in range(1, n):
        assert expected_reward(walk_model(i, n), absorbed) == Fraction(i * (n - i))


def test_expected_reward_infinite_when_not_reached_almost_surely():
    # Single-target walk: from an interior state the target N is reached with prob i/N < 1 (the walk can be
    # absorbed at 0 instead), so the expected time to reach N is infinite -> raises.
    with pytest.raises(ValueError, match="almost surely"):
        expected_reward(walk_model(2, 4), _won(4))


def test_expected_reward_at_target_is_zero():
    win = Choice("win")
    m = Model(init=win, actions=[], terminal=lambda s: True)
    assert expected_reward(m, _win) == Fraction(0)
