"""``Model.footprint`` — memoize an expensive ``actions_fn`` across states that share a footprint,
and ``footprint_sound``, the gate that the memoization is safe."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, Model, check, explore, footprint_sound


@dataclass(frozen=True)
class S:
    a: int  # the menu depends ONLY on this
    b: int  # bounded counter; irrelevant to which actions are offered


def _menu_by_a(calls: list[int]) -> Callable[[S], Iterable[Action[S]]]:
    """An ``actions_fn`` whose MENU depends only on ``a`` (a==0 also offers inc_b), recording each call
    so a test can assert how often it ran. ``enabled``/``apply`` still read the full state."""

    def actions_fn(s: S) -> list[Action[S]]:
        calls.append(s.a)
        acts: list[Action[S]] = [
            Action("cycle_a", enabled=lambda st: True, apply=lambda st: dc_replace(st, a=(st.a + 1) % 3))
        ]
        if s.a == 0:
            acts.append(Action("inc_b", enabled=lambda st: st.b < 2, apply=lambda st: dc_replace(st, b=st.b + 1)))
        return acts

    return actions_fn


def test_footprint_memoizes_actions_fn_once_per_footprint_not_per_state():
    calls: list[int] = []
    model = Model(init=S(0, 0), actions_fn=_menu_by_a(calls), footprint=lambda s: s.a)
    g = explore(model)
    # Full space is still enumerated: a in {0,1,2}, b in {0,1,2} = 9 states (b only grows while a==0).
    assert len(g.states) == 9
    # But actions_fn ran once per DISTINCT footprint (a in {0,1,2}), not once per state.
    assert set(calls) == {0, 1, 2}
    assert len(calls) == 3


def test_without_footprint_actions_fn_runs_once_per_state():
    calls: list[int] = []
    model = Model(init=S(0, 0), actions_fn=_menu_by_a(calls))
    g = explore(model)
    assert len(g.states) == 9
    assert len(calls) == 9  # no memoization: one call per reachable state


def test_footprint_preserves_the_verdict():
    inv: dict[str, Callable[[S], bool]] = {"b-bounded": lambda s: s.b <= 2}
    sound_fp = Model(init=S(0, 0), actions_fn=_menu_by_a([]), footprint=lambda s: s.a, invariants=inv)
    no_fp = Model(init=S(0, 0), actions_fn=_menu_by_a([]), invariants=inv)
    assert check(sound_fp).ok == check(no_fp).ok
    assert check(sound_fp).states_explored == check(no_fp).states_explored


def test_footprint_sound_accepts_a_sound_footprint():
    model = Model(init=S(0, 0), actions_fn=_menu_by_a([]), footprint=lambda s: s.a)
    truthful_states = explore(Model(init=S(0, 0), actions_fn=_menu_by_a([]))).states
    assert footprint_sound(model, truthful_states) is True


def test_footprint_sound_rejects_an_underspecified_footprint():
    # A constant footprint collapses a==0 (offers inc_b) with a!=0 (does not): different menus, one bucket.
    model = Model(init=S(0, 0), actions_fn=_menu_by_a([]), footprint=lambda s: 0)
    truthful_states = explore(Model(init=S(0, 0), actions_fn=_menu_by_a([]))).states
    assert footprint_sound(model, truthful_states) is False


def test_footprint_sound_is_false_without_actions_fn_or_footprint():
    assert footprint_sound(Model(init=S(0, 0), actions=[]), [S(0, 0)]) is False
    assert footprint_sound(Model(init=S(0, 0), actions_fn=_menu_by_a([])), [S(0, 0)]) is False


@dataclass(frozen=True)
class U:
    """A frozen dataclass with a list field: statically Hashable, runtime-unhashable — footprint's
    target case, checked via ``key=``."""

    a: int
    log: list[int]


def test_footprint_memoizes_for_unhashable_states_via_key():
    calls: list[int] = []

    def actions_fn(s: U) -> list[Action[U]]:
        calls.append(s.a)
        return [Action("step", enabled=lambda st: len(st.log) < 2, apply=lambda st: U(a=st.a, log=[*st.log, st.a]))]

    model = Model(init=U(0, []), actions_fn=actions_fn, footprint=lambda s: s.a, terminal=lambda s: len(s.log) >= 2)
    r = check(model, key=lambda s: (s.a, tuple(s.log)))
    assert r.ok
    # a is constant 0, so one footprint: actions_fn ran once despite several states.
    assert set(calls) == {0}
    assert len(calls) == 1
