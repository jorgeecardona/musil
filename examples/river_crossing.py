"""Wolf, goat, cabbage — solving a planning puzzle by reachability.

A farmer must ferry a wolf, a goat, and a cabbage across a river in a boat that holds only the farmer plus
one item. Left unwatched, the wolf eats the goat, or the goat eats the cabbage. Find a sequence of crossings
that gets everything across with nothing eaten.

This is the model checker used as a PLANNER. The trick is to make illegal moves impossible and then ask
whether the goal is reachable:

- Each crossing is guarded so it may fire only if the resulting bank configuration is SAFE (the farmer is
  with the goat, or the wolf is apart from the goat and the goat apart from the cabbage). Unsafe states are
  never entered, so every reachable state is a legal position.
- `witness(graph, everyone_across)` returns the SHORTEST path from the start to a goal state — the plan
  itself, seven crossings. Where `reaches` answers "is the goal reachable?" as a yes/no, `witness` hands back
  the concrete trace, which `format_trace` renders as the step-by-step solution.

Equivalently, one can *refute* the claim "the goal is never reached": give the model the invariant
`not everyone_across` and `check` returns a counterexample whose trace is the same plan. Finding a plan and
refuting "no plan exists" are the same computation.

There is no randomness and no dependency: 10 reachable states, one exact answer.

Run: python examples/river_crossing.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, explore, format_trace, reaches, witness

Side = str  # "L" (near bank) or "R" (far bank)


@dataclass(frozen=True)
class Bank:
    farmer: Side = "L"
    wolf: Side = "L"
    goat: Side = "L"
    cabbage: Side = "L"


GOAL = Bank("R", "R", "R", "R")


def _other(side: Side) -> Side:
    return "R" if side == "L" else "L"


def _safe(s: Bank) -> bool:
    """Nothing gets eaten: the goat is never left with the wolf or the cabbage while the farmer is away."""
    goat_unwatched = s.farmer != s.goat
    return not (goat_unwatched and (s.wolf == s.goat or s.goat == s.cabbage))


def _apply_move(s: Bank, carry: str | None) -> Bank:
    """The farmer rows to the other bank, taking ``carry`` (``None`` = rows alone) along."""
    f = _other(s.farmer)
    if carry == "wolf":
        return replace(s, farmer=f, wolf=_other(s.wolf))
    if carry == "goat":
        return replace(s, farmer=f, goat=_other(s.goat))
    if carry == "cabbage":
        return replace(s, farmer=f, cabbage=_other(s.cabbage))
    return replace(s, farmer=f)


def _present(s: Bank, carry: str | None) -> bool:
    """The farmer can only take something that is on the farmer's own bank."""
    if carry == "wolf":
        return s.wolf == s.farmer
    if carry == "goat":
        return s.goat == s.farmer
    if carry == "cabbage":
        return s.cabbage == s.farmer
    return True  # rowing alone is always possible


def _move(name: str, carry: str | None) -> Action[Bank]:
    # Enabled only when the item is on the farmer's bank AND the resulting state is safe: illegal moves
    # simply do not exist, so every reachable state is a legal position and any path to the goal is a solution.
    return Action(name, enabled=lambda s: _present(s, carry) and _safe(_apply_move(s, carry)), apply=lambda s: _apply_move(s, carry))


RIVER = Model(
    init=Bank(),
    actions=[
        _move("row alone", None),
        _move("take wolf", "wolf"),
        _move("take goat", "goat"),
        _move("take cabbage", "cabbage"),
    ],
    terminal=lambda s: s == GOAL,  # once everyone is across, the puzzle is solved
)


def everyone_across(s: Bank) -> bool:
    return s == GOAL


def _render(s: Bank) -> str:
    return f"farmer={s.farmer}  wolf={s.wolf}  goat={s.goat}  cabbage={s.cabbage}"


if __name__ == "__main__":
    graph = explore(RIVER)
    print(f"reachable (safe) states: {len(graph.states)}")

    plan = witness(graph, everyone_across)
    assert plan is not None, "the goal must be reachable"
    crossings = len(plan) - 1
    print(f"the goal is reachable in {crossings} crossings:\n")
    print(format_trace(plan, render=_render))

    # The classic minimal solution is 7 crossings; the goal is reachable; and no unsafe state is ever
    # reachable (the guards make illegal positions non-existent) -- all exact, from a 10-state search.
    assert crossings == 7
    assert bool(reaches(graph, everyone_across))
    assert all(_safe(s) for s in graph.states)
    print("\nSolved: 7 crossings, nothing eaten — the shortest plan, found by reachability.")
