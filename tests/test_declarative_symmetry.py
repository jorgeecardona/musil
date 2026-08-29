"""``canonical_by_fields`` — declarative symmetry reduction: name the interchangeable-collection fields
and get a sound ``canonicalize``, without hand-writing get/put."""

from __future__ import annotations

from dataclasses import dataclass

from musil import (
    Action,
    Model,
    canonical_by_fields,
    check,
    explore,
    symmetry_reduction_sound,
)


@dataclass(frozen=True)
class W:
    workers: tuple[int, ...]  # interchangeable: worker identities do not matter


def _workers_model(n: int) -> Model[W]:
    acts: list[Action[W]] = [
        Action(
            f"inc{i}",
            enabled=lambda s: True,
            apply=lambda s, i=i: W(tuple((v + 1) % 3 if j == i else v for j, v in enumerate(s.workers))),
        )
        for i in range(n)
    ]
    return Model(
        init=W((0,) * n),
        actions=acts,
        invariants={"bounded": lambda s: all(0 <= v < 3 for v in s.workers)},
        terminal=lambda s: False,
    )


def test_canonical_by_fields_reduces_the_space_and_stays_sound():
    m = _workers_model(3)
    assert len(explore(m).states) == 27  # 3 values ** 3 workers
    canon = canonical_by_fields("workers")
    assert len(explore(m, canonicalize=canon).states) == 10  # multisets of size 3 over 3 values
    assert symmetry_reduction_sound(m, canon)
    assert check(m, canonicalize=canon).ok


def test_canonical_by_fields_sorts_each_named_dataclass_field():
    @dataclass(frozen=True)
    class St:
        a: tuple[int, ...]
        b: tuple[int, ...]
        leader: int  # left untouched

    canon = canonical_by_fields("a", "b")
    assert canon(St(a=(3, 1, 2), b=(2, 1), leader=0)) == St(a=(1, 2, 3), b=(1, 2), leader=0)


def test_canonical_by_fields_uses_model_copy_for_pydantic_states():
    # A pydantic v2 model exposes model_copy(update=...); canonical_by_fields must use it (not replace).
    # Simulated without the dependency.
    class FakeModel:
        def __init__(self, xs: tuple[int, ...]) -> None:
            self.xs = xs

        def model_copy(self, *, update: dict[str, object]) -> FakeModel:
            m = FakeModel(self.xs)
            for k, v in update.items():
                setattr(m, k, v)
            return m

    out = canonical_by_fields("xs")(FakeModel((3, 1, 2)))
    assert out.xs == (1, 2, 3)


@dataclass(frozen=True)
class P:
    workers: tuple[int, ...]


def _order_sensitive_model() -> Model[P]:
    # Two workers toggling 0<->1, with an invariant that forbids the ORDERED pair (1, 0). That
    # invariant is not symmetric, so sorting workers hides the (1,0) violation (its sorted form (0,1)
    # holds), which is exactly the unsoundness the gate must reject.
    n = 2
    acts: list[Action[P]] = [
        Action(
            f"toggle{i}",
            enabled=lambda s: True,
            apply=lambda s, i=i: P(tuple(1 - v if j == i else v for j, v in enumerate(s.workers))),
        )
        for i in range(n)
    ]
    return Model(
        init=P((0, 0)),
        actions=acts,
        invariants={"not_1_0": lambda s: s.workers != (1, 0)},  # order-sensitive → not class-constant under sort
        terminal=lambda s: False,
    )


def test_canonical_by_fields_is_flagged_unsound_when_the_invariant_is_order_sensitive():
    # Declarative does not mean automatically sound: sorting hides the (1,0) violation, and the gate
    # must catch it (exactly why the obligation to run symmetry_reduction_sound remains).
    assert symmetry_reduction_sound(_order_sensitive_model(), canonical_by_fields("workers")) is False
