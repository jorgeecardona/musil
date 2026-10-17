"""``musil.faults`` — the ``once`` / ``budget`` fault combinators.

``crash_actions`` / ``partition_actions`` are exercised through the distributed examples; these tests
cover the one-shot latch and bounded budget that keep a fault model finite without the caller
hand-writing ``*_done`` fields and re-fire guards."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

import pytest

from musil import Action, Model, check, explore
from musil.faults import budget, once


@dataclass(frozen=True)
class Glitch:
    n: int = 0
    glitched: bool = False
    spent: int = 0


def _raw_glitch() -> Action[Glitch]:
    # unbounded on its own: always enabled, so n grows without limit
    return Action("glitch", enabled=lambda s: True, apply=lambda s: replace(s, n=s.n + 1))


def test_once_fires_at_most_once() -> None:
    latched = once(
        _raw_glitch(),
        fired=lambda s: s.glitched,
        mark=lambda s: replace(s, glitched=True),
    )
    # terminal=all: the fault-only model is absorbing once the latch trips (no deadlock to report),
    # so check exercises the invariant, not a dead-end
    model = Model(
        init=Glitch(),
        actions=[latched],
        invariants={"bounded": lambda s: s.n <= 1},
        terminal=lambda s: True,
    )
    graph = explore(model)

    # the latch bounds the space: n never passes 1, and both outcomes are reached
    assert all(s.n <= 1 for s in graph.states)
    assert any(s.n == 1 and s.glitched for s in graph.states)
    assert check(model).ok


def test_once_preserves_name_and_fairness() -> None:
    base: Action[Glitch] = Action("glitch", enabled=lambda s: True, apply=lambda s: s, fair="weak")
    latched = once(base, fired=lambda s: s.glitched, mark=lambda s: replace(s, glitched=True))
    assert latched.name == "glitch"
    assert latched.fair == "weak"


def test_budget_fires_at_most_n_times() -> None:
    bounded = budget(
        _raw_glitch(),
        3,
        count=lambda s: s.spent,
        tick=lambda s: replace(s, spent=s.spent + 1),
    )
    model = Model(
        init=Glitch(),
        actions=[bounded],
        invariants={"bounded": lambda s: s.n <= 3},
        terminal=lambda s: True,
    )
    graph = explore(model)

    # exactly 4 states (0..3 firings); n and spent move together and stop at 3
    assert {s.n for s in graph.states} == {0, 1, 2, 3}
    assert all(s.spent == s.n for s in graph.states)
    assert check(model).ok


def test_budget_zero_disables_the_action() -> None:
    bounded = budget(
        _raw_glitch(),
        0,
        count=lambda s: s.spent,
        tick=lambda s: replace(s, spent=s.spent + 1),
    )
    graph = explore(Model(init=Glitch(), actions=[bounded]))
    assert [s.n for s in graph.states] == [0]  # never fires


def test_budget_negative_raises() -> None:
    with pytest.raises(ValueError, match="budget n must be >= 0"):
        budget(
            _raw_glitch(), -1, count=lambda s: s.spent, tick=lambda s: replace(s, spent=s.spent + 1)
        )


@dataclass(frozen=True)
class Pair:
    a: int = 0
    b: int = 0
    spent: int = 0


def test_budget_shared_pool_across_actions() -> None:
    # one counter, two actions: their COMBINED firings are bounded by the single budget of 2
    count: Callable[[Pair], int] = lambda s: s.spent  # noqa: E731
    tick: Callable[[Pair], Pair] = lambda s: replace(s, spent=s.spent + 1)  # noqa: E731
    bump_a = budget(
        Action[Pair]("a", enabled=lambda s: True, apply=lambda s: replace(s, a=s.a + 1)),
        2,
        count=count,
        tick=tick,
    )
    bump_b = budget(
        Action[Pair]("b", enabled=lambda s: True, apply=lambda s: replace(s, b=s.b + 1)),
        2,
        count=count,
        tick=tick,
    )
    graph = explore(Model(init=Pair(), actions=[bump_a, bump_b]))

    # a + b counts the firings; the shared pool caps the total at 2, never per-action at 2
    assert all(s.a + s.b == s.spent and s.spent <= 2 for s in graph.states)
    assert any(s.a == 2 for s in graph.states)  # all budget to a
    assert any(s.a == 1 and s.b == 1 for s in graph.states)  # split between a and b
