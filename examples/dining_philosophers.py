"""Dining philosophers -- the classic deadlock, found and then fixed.

N philosophers sit around a table with one fork between each pair; a philosopher needs BOTH adjacent
forks to eat. The naive protocol -- pick up your left fork, then your right -- has a fatal
interleaving: if everyone grabs their left fork at once, everyone then waits forever for a right fork
their neighbour is holding. No invariant is violated; the system simply wedges. musil reports it as a
DEADLOCK (a non-terminal state with no enabled action) and prints the shortest path into it.

The fix is the resource-hierarchy rule: always pick up the lower-numbered fork first. That breaks the
circular wait, and musil confirms the fixed protocol has no reachable deadlock.

Run: python examples/dining_philosophers.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check

N = 3  # philosophers (and forks); 3 is the smallest table that exhibits the circular wait


@dataclass(frozen=True)
class Table:
    """Who holds each fork: ``forks[f]`` is the index of the philosopher holding fork ``f``, or None
    if it lies on the table. Philosopher ``i`` sits between fork ``i`` (left) and ``(i + 1) % N`` (right)."""

    forks: tuple[int | None, ...] = (None,) * N


def _set(seq: tuple[int | None, ...], i: int, val: int | None) -> tuple[int | None, ...]:
    return (*seq[:i], val, *seq[i + 1 :])


def _philosopher_actions(i: int, first: int, second: int) -> list[Action[Table]]:
    """Three steps for philosopher ``i``: take the ``first`` fork, take the ``second`` (now eating),
    then put both down. ``first``/``second`` are fork indices in the order this philosopher grabs them."""
    return [
        Action(
            f"P{i}_take_f{first}",
            lambda s: s.forks[first] is None and i not in s.forks,
            lambda s: replace(s, forks=_set(s.forks, first, i)),
        ),
        Action(
            f"P{i}_take_f{second}",
            lambda s: s.forks[first] == i and s.forks[second] is None,
            lambda s: replace(s, forks=_set(s.forks, second, i)),
        ),
        Action(
            f"P{i}_eat_release",
            lambda s: s.forks[first] == i and s.forks[second] == i,
            lambda s: replace(s, forks=_set(_set(s.forks, first, None), second, None)),
        ),
    ]


def _model(*, ordered: bool) -> Model[Table]:
    actions: list[Action[Table]] = []
    for i in range(N):
        left, right = i, (i + 1) % N
        # naive: everyone grabs their LEFT fork first. ordered: everyone grabs the LOWER-numbered
        # fork first (the resource hierarchy that rules out a circular wait).
        first, second = (min(left, right), max(left, right)) if ordered else (left, right)
        actions += _philosopher_actions(i, first, second)
    return Model(init=Table(), actions=actions)


def naive_model() -> Model[Table]:
    return _model(ordered=False)


def ordered_model() -> Model[Table]:
    return _model(ordered=True)


def main() -> int:
    print(f"=== naive (everyone takes their LEFT fork first), N={N} ===")
    print(check(naive_model()))
    print(f"\n=== resource-ordered (lower-numbered fork first), N={N} ===")
    print(check(ordered_model()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
