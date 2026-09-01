"""Monty Hall — the famous 2/3-vs-1/3 result, as exact fractions.

Three doors, a car behind one, goats behind the others. You pick a door; the host (who knows where the car
is) opens a *different* door showing a goat; you may keep your door or switch to the remaining one. Switching
wins with probability 2/3, keeping wins with 1/3 — the counterintuitive answer that fooled a generation of
readers. `musil.probabilistic` derives it exactly, as `fractions.Fraction`, no sampling and no floating point.

Two things make this a clean model-checking example:

- It is TWO DTMCs, one per strategy (STAY, SWITCH), not one MDP. musil's MDP policies are state-based and the
  state carries `car`, so an MDP policy could "observe" the car and trivially win — but the real player
  CANNOT see the car when deciding. Fixing the strategy in the model structure (only `stay`, or only
  `switch`, is ever enabled) encodes exactly that partial observability. The strategy is chosen in advance.
- All the branching is uniform, so no `weight` function is needed: the car is placed uniformly (1/3 each),
  and when your first pick happens to hide the car the host chooses uniformly between the two goats (1/2).

The player's initial pick is fixed at door 1 with no loss of generality (the doors are symmetric).

Run: python examples/monty_hall.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from musil import Action, Model
from musil.probabilistic import assert_probability, reach_probability

PICK = 1  # your initial choice, fixed by symmetry: doors are interchangeable


@dataclass(frozen=True)
class Game:
    car: int = 0  # door hiding the car (1..3); 0 until placed
    opened: int = 0  # goat door the host opened (2 or 3); 0 until opened
    final: int = 0  # your final door (1..3); 0 until you decide


def _place(d: int) -> Action[Game]:
    """Place the car behind door ``d``. Three such actions, equally weighted -> P = 1/3 each."""
    return Action(f"car{d}", enabled=lambda s: s.car == 0, apply=lambda s: replace(s, car=d))


def _open(o: int) -> Action[Game]:
    """The host opens door ``o`` (a goat): enabled only once the car is placed, when ``o`` is neither your
    pick (door 1) nor the car. If your pick hides the car BOTH goat doors qualify -> the host picks uniformly
    (1/2 each); otherwise exactly one door qualifies (the host is forced)."""
    return Action(f"open{o}", enabled=lambda s: s.car != 0 and s.opened == 0 and o != s.car, apply=lambda s: replace(s, opened=o))


def _decision(s: Game) -> bool:
    return s.opened != 0 and s.final == 0


# STAY keeps door 1; SWITCH moves to the one door that is neither your pick nor the opened goat. With
# PICK = 1 and opened in {2, 3}, that door is 5 - opened. Only ONE of these is ever enabled in a given model,
# so the strategy cannot depend on where the car is.
STAY: Action[Game] = Action("stay", enabled=_decision, apply=lambda s: replace(s, final=PICK))
SWITCH: Action[Game] = Action("switch", enabled=_decision, apply=lambda s: replace(s, final=5 - s.opened))


def _game(decide: Action[Game]) -> Model[Game]:
    return Model(
        init=Game(),
        actions=[_place(1), _place(2), _place(3), _open(2), _open(3), decide],
        terminal=lambda s: s.final != 0,  # once you have decided, the game is over (an absorbing state)
    )


STAY_GAME = _game(STAY)
SWITCH_GAME = _game(SWITCH)


def won(s: Game) -> bool:
    return s.final != 0 and s.final == s.car


if __name__ == "__main__":
    p_stay = reach_probability(STAY_GAME, won)
    p_switch = reach_probability(SWITCH_GAME, won)
    print(f"P(win | stay)   = {p_stay}")  # 1/3
    print(f"P(win | switch) = {p_switch}")  # 2/3

    # Exact rational arithmetic -- assert the closed forms, no floating point.
    assert_probability(p_stay, equals=Fraction(1, 3), label="P(win | stay)")
    assert_probability(p_switch, equals=Fraction(2, 3), label="P(win | switch)")
    assert p_switch == 2 * p_stay  # switching is exactly twice as good
    assert p_stay + p_switch == 1  # the car is always behind the stayed door or the switched one
    print("\nSwitching wins exactly twice as often (2/3 vs 1/3) -- exact, no sampling.")
