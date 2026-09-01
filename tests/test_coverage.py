"""Action coverage: a green check does not say the behaviour you wrote was ever explored."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from musil import Action, Model, check, explore
from musil.metrics import coverage, coverage_of
from musil.symmetry import canonical_by_sorting


@dataclass(frozen=True)
class Light:
    color: str = "red"


def _light(*extra: Action[Light]) -> Model[Light]:
    return Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("stop", lambda s: s.color == "green", lambda _s: Light("red")),
            *extra,
        ],
    )


def test_a_healthy_model_flags_nothing() -> None:
    cov = coverage(_light())
    assert cov.ok
    assert cov.actions_total == 2
    assert cov.dead_actions == cov.always_enabled_actions == cov.stutter_only_actions == ()
    assert "all 2 actions fire and move" in str(cov)


def test_an_unsatisfiable_guard_is_named_dead_while_check_still_passes() -> None:
    # the point of the whole thing: check is green, and one action never ran
    model = _light(Action("flash", lambda s: s.color == "blue", lambda _s: Light("red")))
    assert check(model).ok

    cov = coverage(model)
    assert cov.dead_actions == ("flash",)
    assert not cov.ok
    assert "never enabled (dead): flash" in str(cov)


def test_an_always_enabled_action_is_named() -> None:
    cov = coverage(_light(Action("crash", lambda _s: True, lambda _s: Light("off"))))
    # 'crash' fires everywhere including from off, so every reachable state has it enabled
    assert "crash" in cov.always_enabled_actions
    assert "the guard never guards" in str(cov)


def test_an_action_that_only_self_loops_is_named() -> None:
    cov = coverage(_light(Action("idle", lambda _s: True, lambda s: s)))
    assert cov.stutter_only_actions == ("idle",)
    assert "idle" in cov.always_enabled_actions  # it is both, and both are reported


def test_a_terminal_state_means_nothing_is_always_enabled() -> None:
    # a terminal state has no enabled action, so no action can be enabled everywhere. Empty here is
    # correct, not a missed detection.
    model = Model(
        init=Light("red"),
        actions=[
            Action("off", lambda s: s.color == "red", lambda _s: Light("off")),
            Action("anytime", lambda s: s.color == "red", lambda _s: Light("red")),
        ],
        terminal=lambda s: s.color == "off",
    )
    cov = coverage(model)
    assert cov.always_enabled_actions == ()
    assert cov.dead_actions == ()


def test_truncation_downgrades_dead_to_not_yet_seen() -> None:
    @dataclass(frozen=True)
    class N:
        n: int = 0

    model = Model(
        init=N(0),
        actions=[
            Action("inc", lambda _s: True, lambda s: N(s.n + 1)),
            Action("never", lambda s: s.n < 0, lambda s: s),
        ],
    )
    cov = coverage(model, max_states=20)
    assert cov.truncated
    assert cov.dead_actions == ("never",)  # still reported...
    assert "INCONCLUSIVE" in str(cov)  # ...but the rendering refuses to call it dead
    assert "not yet seen enabled" in str(cov)


def test_coverage_of_reuses_an_explored_graph() -> None:
    model = _light(Action("flash", lambda s: s.color == "blue", lambda _s: Light("red")))
    graph = explore(model)
    assert coverage_of(graph, model) == coverage(model)


def test_coverage_is_correct_under_symmetry_reduction() -> None:
    """Reading the graph's edges rather than re-applying actions is what makes this hold: a reduced
    graph stores canonical successors, so re-running `apply` and comparing would misjudge which
    firings moved."""

    @dataclass(frozen=True)
    class Workers:
        counts: tuple[int, ...] = (0, 0, 0)

    def step(i: int) -> Action[Workers]:
        return Action(
            f"w{i}:step",
            lambda s: s.counts[i] < 2,
            lambda s: replace(s, counts=(*s.counts[:i], s.counts[i] + 1, *s.counts[i + 1 :])),
        )

    model = Model(init=Workers(), actions=[step(i) for i in range(3)])
    canon: Callable[[Workers], Workers] = canonical_by_sorting(
        get=lambda s: s.counts, put=lambda s, xs: replace(s, counts=xs)
    )
    reduced = coverage_of(explore(model, canonicalize=canon), model)

    # under the quotient a worker's step can land back on the same canonical state (it swapped two
    # interchangeable workers) -- but no worker is dead, and none only self-loops
    assert reduced.dead_actions == ()
    assert reduced.stutter_only_actions == ()
    assert coverage_of(explore(model), model).ok
