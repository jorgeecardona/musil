"""Metamorphic property test for partial-order reduction's SOUNDNESS GATE, over many random models and ample
functions (fixed seed, pure stdlib). POR is the most dangerous feature to get wrong: an unsound reduction
silently drops the path to a violation and turns a real bug into a green check. `por_sound` is the gate that
must catch that. The property this pins, on every random (model, ample):

- **POR never invents a state** — the reduced reachable set is always a subset of the full one.
- **the gate has no false positive** — whenever the reduction FLIPS the safety verdict (`check` on the reduced
  graph disagrees with `check` on the full model), `por_sound` MUST return False. Equivalently:
  `por_sound(model, ample) == True` implies the verdict is preserved.

The other soundness-critical layers (probabilistic, core/LTL, liveness) already have such a sweep; this gives
POR the same broad guard, complementing the fixed cases in `test_por.py`.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from musil import Action, Model, check, check_of, explore, explore_por, por_sound


@dataclass(frozen=True)
class St:
    c: tuple[int, ...]


def _inc(i: int, cap: int) -> Action[St]:
    return Action(f"a{i}", enabled=lambda s: s.c[i] < cap, apply=lambda s: St((*s.c[:i], s.c[i] + 1, *s.c[i + 1:])))


def _random_model(rng: random.Random) -> Model[St]:
    """A small concurrent model: n counters each incremented independently (up to `cap`), plus a `noop`
    self-loop (so an ample that fires only it gets stuck short of a violation). The invariant `sum != target`
    is violable when `target` is a reachable sum and holds when it isn't — a mix of ok / not-ok models."""
    n, cap = rng.randint(1, 3), rng.randint(1, 3)
    actions: list[Action[St]] = [_inc(i, cap) for i in range(n)]
    actions.append(Action("noop", enabled=lambda _s: True, apply=lambda s: s))
    target = rng.randint(0, n * cap + 1)  # target > n*cap is unreachable -> the invariant holds
    return Model(
        init=St((0,) * n),
        actions=actions,
        invariants={"sum": lambda s, t=target: sum(s.c) != t},
        terminal=lambda _s: False,
    )


def _ample_family(rng: random.Random) -> list[Callable[[St, tuple[Action[St], ...]], Iterable[Action[St]]]]:
    """A mix of ample functions, some sound and some deliberately unsound, so the gate is exercised in both
    directions. Each is a DETERMINISTIC function of the state (POR requires a stable choice per state)."""
    seed = rng.randrange(1 << 30)

    def rand_subset(s: St, enabled: tuple[Action[St], ...]) -> list[Action[St]]:
        if not enabled:
            return []
        h = hash((seed, s)) & 0x7FFFFFFF
        k, idx = 1 + (h % len(enabled)), h % len(enabled)
        rotated = enabled[idx:] + enabled[:idx]
        return list(rotated[:k])

    def prefer_noop(_s: St, enabled: tuple[Action[St], ...]) -> list[Action[St]]:  # often unsound: gets stuck
        noops = [a for a in enabled if a.name == "noop"]
        return noops if noops else list(enabled)

    def drop_first(_s: St, enabled: tuple[Action[St], ...]) -> list[Action[St]]:  # can drop the critical action
        return list(enabled[1:]) if len(enabled) > 1 else list(enabled)

    return [rand_subset, prefer_noop, drop_first]


def test_por_sound_gate_has_no_false_positive_over_random_models() -> None:
    rng = random.Random(24)
    saw_sound = saw_flip = 0
    for _ in range(80):
        model = _random_model(rng)
        full_states = set(explore(model).states)
        full_ok = check(model).ok
        for ample in _ample_family(rng):
            reduced = explore_por(model, ample=ample)
            assert set(reduced.states) <= full_states  # POR never invents a state
            reduced_ok = check_of(reduced, model).ok
            approved = por_sound(model, ample)
            if approved:
                saw_sound += 1
                assert reduced_ok == full_ok  # a gate-approved reduction must preserve the safety verdict
            if reduced_ok != full_ok:  # the reduction dropped (or invented) a violation -> unsound
                saw_flip += 1
                assert not approved  # the gate MUST have rejected it (no false positive)
    # the sweep genuinely exercised both directions, not just the trivial all-sound case
    assert saw_sound > 0 and saw_flip > 0
