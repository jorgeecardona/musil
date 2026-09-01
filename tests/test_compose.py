"""Parallel composition: the interleaving product of independent component models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from musil import Action, Model, check
from musil.compose import compose


@dataclass(frozen=True)
class Toggle:
    on: bool = False


def _toggle() -> Model[Toggle]:
    return Model(
        init=Toggle(False),
        actions=[
            Action("on", lambda s: not s.on, lambda _s: Toggle(True)),
            Action("off", lambda s: s.on, lambda _s: Toggle(False)),
        ],
    )


def test_compose_explores_the_full_interleaving() -> None:
    model = compose({"a": _toggle(), "b": _toggle()})
    result = check(model)
    assert result.ok
    assert result.states_explored == 4  # 2 x 2 joint states, all reachable by interleaving


def test_joint_invariant_sees_a_cross_component_state() -> None:
    # an invariant spanning both components catches the interleaving where both advance
    model = compose(
        {"a": _toggle(), "b": _toggle()},
        # __getitem__ returns the component state as Hashable; cast back to read its fields
        invariants={"not-both-on": lambda s: not (cast(Toggle, s["a"]).on and cast(Toggle, s["b"]).on)},
    )
    result = check(model)
    assert not result.ok
    assert result.invariant == "not-both-on"


def test_component_invariants_are_lifted_and_checked() -> None:
    @dataclass(frozen=True)
    class Counter:
        n: int = 0

    bad = Model(
        init=Counter(0),
        actions=[Action("inc", lambda s: s.n < 2, lambda s: Counter(s.n + 1))],
        invariants={"under-2": lambda s: s.n < 2},  # violated once it reaches 2
        terminal=lambda s: s.n == 2,
    )
    result = check(compose({"c": bad, "t": _toggle()}))
    assert not result.ok
    assert result.invariant == "c:under-2"  # the component invariant, name-qualified


def test_composite_is_terminal_only_when_all_parts_are() -> None:
    @dataclass(frozen=True)
    class OneShot:
        done: bool = False

    one = Model(
        init=OneShot(False),
        actions=[Action("finish", lambda s: not s.done, lambda _s: OneShot(True))],
        terminal=lambda s: s.done,
    )
    model = compose({"x": one, "y": one})
    result = check(model)
    assert result.ok  # no deadlock: composite terminal only at (done, done), reached cleanly
    assert result.states_explored == 4
