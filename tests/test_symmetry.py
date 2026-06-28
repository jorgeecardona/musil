"""Symmetry reduction: opt-in `canonicalize` on check/explore, validated by `symmetry_reduction_sound`."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Invariant, Model, check, explore, symmetry_reduction_sound


@dataclass(frozen=True)
class Pair:
    a: int = 0
    b: int = 0


def _model(invariant_ok: bool = True) -> Model[Pair]:
    # two interchangeable workers, each counts 0 -> 1 -> 2; the model is symmetric under swapping a,b
    inv: dict[str, Invariant[Pair]] = {} if invariant_ok else {"sum-le-3": lambda s: s.a + s.b <= 3}
    return Model(
        init=Pair(),
        actions=[
            Action("a:step", lambda s: s.a < 2, lambda s: replace(s, a=s.a + 1)),
            Action("b:step", lambda s: s.b < 2, lambda s: replace(s, b=s.b + 1)),
        ],
        invariants=inv,
    )


def _sort_pair(s: Pair) -> Pair:
    lo, hi = sorted((s.a, s.b))
    return Pair(lo, hi)


def test_reduction_shrinks_state_space() -> None:
    full = explore(_model()).states
    reduced = explore(_model(), canonicalize=_sort_pair).states
    assert len(full) == 9  # (a,b) in 0..2 x 0..2
    assert len(reduced) == 6  # unordered pairs: 00,01,02,11,12,22
    assert all(s.a <= s.b for s in reduced)  # every state is a sorted representative


def test_valid_symmetry_passes_the_soundness_gate() -> None:
    assert symmetry_reduction_sound(_model(), _sort_pair)
    assert symmetry_reduction_sound(_model(invariant_ok=False), _sort_pair)


def test_reduced_check_finds_the_same_violation() -> None:
    full = check(_model(invariant_ok=False))
    reduced = check(_model(invariant_ok=False), canonicalize=_sort_pair)
    assert not full.ok and not reduced.ok
    assert full.invariant == reduced.invariant == "sum-le-3"  # (2,2): sum 4 > 3, found both ways


def test_gate_catches_a_lossy_projection_canonicalizer() -> None:
    # projecting away `b` (mapping (a,b) -> (a,0)) is NOT a real symmetry: it merges states that
    # differ in b. Coverage alone would pass, but an invariant on b is hidden — the gate must fail.
    def project_a(s: Pair) -> Pair:
        return Pair(s.a, 0)

    model = Model(
        init=Pair(),
        actions=[
            Action("a:step", lambda s: s.a < 2, lambda s: replace(s, a=s.a + 1)),
            Action("b:step", lambda s: s.b < 2, lambda s: replace(s, b=s.b + 1)),
        ],
        invariants={"b-le-1": lambda s: s.b <= 1},  # violated at b==2 — invisible under project_a
    )
    # the reduction would WRONGLY pass (reps have b=0, never violating), so the gate must reject it
    assert not symmetry_reduction_sound(model, project_a)
