"""New ergonomics: key= (non-hashable states), actions_fn (state-dependent actions), distinct_by callable,
format_trace render/diff, and ActionSchema/enumerate_actions (bounded parameterized action algebra)."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

import pytest

from musil import Action, Invariant, Model, check, check_all, explore, format_trace
from musil.core import ActionSchema, enumerate_actions, format_trace_diff


@dataclass(frozen=True)
class Bag:
    n: int
    xs: list[int]  # a list field → the frozen dataclass is NOT hashable (hash() raises)


def _bag_model(invariants: dict[str, Invariant[Bag]]) -> Model[Bag]:
    return Model(
        init=Bag(0, []),
        actions=[Action("inc", lambda b: b.n < 3, lambda b: Bag(b.n + 1, [*b.xs, b.n]))],
        invariants=invariants,
        terminal=lambda b: b.n == 3,
    )


def _bag_key(b: Bag) -> tuple[int, tuple[int, ...]]:
    return (b.n, tuple(b.xs))


# --- #1 key= : check / check_all accept non-hashable states -------------------------------------
def test_unhashable_state_needs_key():
    with pytest.raises(TypeError):  # hash(Bag(...)) raises → no key means the visited-set blows up
        check(_bag_model({"ok": lambda b: True}))


def test_key_lets_check_run_on_unhashable_state_and_trace_is_rich():
    assert check(_bag_model({"n_le_3": lambda b: b.n <= 3}), key=_bag_key).ok
    r = check(_bag_model({"n_le_1": lambda b: b.n <= 1}), key=_bag_key)
    assert not r.ok and r.invariant == "n_le_1"
    assert isinstance(r.trace[-1].state, Bag) and r.trace[-1].state.n == 2  # rich state, not the key tuple


def test_key_works_for_check_all():
    viols = check_all(_bag_model({"n_le_1": lambda b: b.n <= 1}), key=_bag_key)
    assert [v.invariant for v in viols] == ["n_le_1"]
    assert isinstance(viols[0].trace[-1].state, Bag)


def test_pydantic_like_state_is_a_single_state_not_a_collection():
    # A pydantic v2 model is iterable (yields (field, value) pairs) and has `model_fields`; it must be treated
    # as ONE state, not shredded by initial_states. (Simulated here without a pydantic dependency.)
    class FakeModel:
        model_fields: ClassVar[dict[str, object]] = {}

        def __iter__(self) -> Iterator[tuple[str, int]]:
            return iter([("a", 1)])

    fm = FakeModel()
    # ONE state kept whole — not shredded into (field, value) tuples despite being iterable.
    assert Model(init=fm, actions=[], terminal=lambda s: True).initial_states() == (fm,)


# --- #2 actions_fn : state-dependent action space -----------------------------------------------
@dataclass(frozen=True)
class C:
    n: int


def test_actions_fn_drives_check_and_explore():
    def acts(s: C) -> list[Action[C]]:
        if s.n < 2:
            return [Action("inc", lambda x: True, lambda x: C(x.n + 1))]
        return [Action("reset", lambda x: True, lambda x: C(0))]

    m = Model(init=C(0), actions_fn=acts, invariants={"ok": lambda s: True}, terminal=lambda s: False)
    assert check(m).ok
    assert {s.n for s in explore(m).states} == {0, 1, 2}  # 0→1→2→(reset)→0, closed


# --- #3 distinct_by callable : bucket violations by class ----------------------------------------
def test_check_all_distinct_by_callable():
    def rule(s: C) -> bool | str:
        return f"n is {s.n}" if s.n >= 2 else True  # reason embeds the variable n

    def parity_of(_name: str, reason: str | None) -> int:
        assert reason is not None
        return int(reason.split()[-1]) % 2

    m = Model(init=C(0), actions=[Action("inc", lambda s: s.n < 5, lambda s: C(s.n + 1))],
              invariants={"rule": rule}, terminal=lambda s: s.n == 5)
    assert len(check_all(m, distinct_by="reason")) == 4          # n=2,3,4,5 each distinct
    assert len(check_all(m, distinct_by="invariant")) == 1       # one invariant name
    assert len(check_all(m, distinct_by=lambda name, reason: name)) == 1
    parity = check_all(m, distinct_by=parity_of)
    assert len(parity) == 2                                      # even {2,4}, odd {3,5}


# --- #4 format_trace render + format_trace_diff --------------------------------------------------
@dataclass(frozen=True)
class Pair:
    a: int
    b: int


def test_format_trace_render_and_diff():
    m = Model(init=Pair(0, 0), actions=[Action("inc_a", lambda s: s.a < 2, lambda s: Pair(s.a + 1, s.b))],
              invariants={"a_le_1": lambda s: s.a <= 1}, terminal=lambda s: False)
    r = check(m)
    assert not r.ok
    txt = format_trace(r.trace, render=lambda s: f"a={s.a}")
    assert "Init: a=0" in txt and "a=2" in txt
    lines = format_trace_diff(r.trace).splitlines()
    assert "a=" in lines[0] and "b=" in lines[0]                 # init shows all fields
    assert all("b=" not in ln for ln in lines[1:])               # steps show only the CHANGED field (a)
    assert any("a=1" in ln for ln in lines[1:])


# --- #5 ActionSchema + enumerate_actions ---------------------------------------------------------
@dataclass(frozen=True)
class Grid:
    vals: tuple[tuple[int, str], ...]


def _grid_add(s: Grid, x: int, y: str) -> Grid:
    return Grid((*s.vals, (x, y)))


def _grid_add_sorted(s: Grid, x: int, y: str) -> Grid:
    return Grid(tuple(sorted((*s.vals, (x, y)))))


def _grid_add_enabled(s: Grid, x: int, y: str) -> bool:
    return (x, y) not in s.vals


def _grid_noop(s: Grid) -> Grid:
    return s


def test_enumerate_actions_cartesian_product_and_zero_param():
    sch = ActionSchema(
        name="add",
        params={"x": [1, 2], "y": ["a", "b"]},
        apply=_grid_add,
        enabled=_grid_add_enabled,
    )
    acts = enumerate_actions([sch])
    assert len(acts) == 4 and all(a.name.startswith("add{") for a in acts)
    z = enumerate_actions([ActionSchema(name="noop", apply=_grid_noop)])
    assert len(z) == 1 and z[0].name == "noop"


def test_enumerate_actions_drives_a_bounded_algebra():
    sch = ActionSchema(
        name="add",
        params={"x": [1, 2], "y": ["a", "b"]},
        apply=_grid_add_sorted,
        enabled=_grid_add_enabled,
    )
    m = Model(init=Grid(()), actions=enumerate_actions([sch]),
              invariants={"ok": lambda s: True}, terminal=lambda s: len(s.vals) == 4)
    r = check(m)
    assert r.ok  # all 4 (x,y) pairs reachable, terminal at the full set
