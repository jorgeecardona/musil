"""Partial-order reduction: the independence test, explore_por mechanism, and the por_sound gate."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, Invariant, Model, explore
from musil.por import explore_por, independent, por_sound


@dataclass(frozen=True)
class Two:
    a: int
    b: int


def _inc_a() -> Action[Two]:
    return Action("inc_a", enabled=lambda s: s.a < 2, apply=lambda s: dc_replace(s, a=s.a + 1))


def _inc_b() -> Action[Two]:
    return Action("inc_b", enabled=lambda s: s.b < 2, apply=lambda s: dc_replace(s, b=s.b + 1))


def _model(inv: dict[str, Invariant[Two]]) -> Model[Two]:
    return Model(init=Two(0, 0), actions=[_inc_a(), _inc_b()], invariants=inv, terminal=lambda s: False)


def test_independent_commuting_conflicting_and_disabled():
    # inc_a and inc_b touch different fields -> independent (commute, neither disables the other)
    assert independent(_inc_a(), _inc_b(), Two(0, 0))
    # two writes to the same field do NOT commute
    set0 = Action[Two]("set0", enabled=lambda s: True, apply=lambda s: dc_replace(s, a=0))
    set1 = Action[Two]("set1", enabled=lambda s: True, apply=lambda s: dc_replace(s, a=1))
    assert not independent(set0, set1, Two(0, 0))
    # independence is defined only for co-enabled actions: inc_a is disabled at a==2
    assert not independent(_inc_a(), _inc_b(), Two(2, 0))


def test_explore_por_with_the_trivial_ample_equals_explore():
    m = _model({})
    full = explore(m)
    reduced = explore_por(m, ample=lambda state, enabled: enabled)
    assert set(reduced.states) == set(full.states)  # a,b in 0..2 = 9 states
    assert len(full.states) == 9


def _inc_a_first(state: Two, enabled: tuple[Action[Two], ...]) -> Iterable[Action[Two]]:
    # a sound ample for these INDEPENDENT actions: fire inc_a alone whenever it is enabled, else fire the
    # rest. Exploring one order of independent actions suffices to preserve the invariants.
    a_actions = [a for a in enabled if a.name == "inc_a"]
    return a_actions or enabled


def test_por_sound_accepts_the_trivial_and_a_real_reduction():
    # invariant a+b != 3: violated at (2,1) and (1,2); the inc_a-first reduction still reaches (2,1),
    # so the violation is preserved even though fewer states are explored.
    m = _model({"sum-not-3": lambda s: s.a + s.b != 3})
    assert por_sound(m, lambda state, enabled: enabled)  # trivial ample: sound by definition
    assert por_sound(m, _inc_a_first)  # a genuine reduction that preserves the bug
    assert len(explore_por(m, ample=_inc_a_first).states) < len(explore(m).states)  # it really reduces


def test_por_sound_rejects_an_ample_that_drops_a_violation():
    # invariant b != 2: reachable only by firing inc_b twice. An ample that never fires inc_b hides it.
    m = _model({"b-not-2": lambda s: s.b != 2})

    def never_inc_b(state: Two, enabled: tuple[Action[Two], ...]) -> Iterable[Action[Two]]:
        return [a for a in enabled if a.name != "inc_b"]

    assert not por_sound(m, never_inc_b)  # the gate catches the dropped violation
