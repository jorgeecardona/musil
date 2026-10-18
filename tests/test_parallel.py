"""Parallel exploration (#17): `check(workers=N)` fans the BFS across fork processes and must return
the SAME Result as the serial sweep — same verdict, same shortest counterexample. Every test asserts
that equality on a model that exercises a different outcome (ok / invariant / deadlock / edge-invariant /
symmetry / non-hashable key). Models and their state types are module-level so fork workers inherit
them and the states pickle across the per-level barrier.

On a platform without `fork`, `check(workers=N)` falls back to the serial sweep, so these still pass;
they only parallelise for real on POSIX."""

from __future__ import annotations

from dataclasses import dataclass

from musil.core import Action, EdgeInvariant, Invariant, Model, check

WORKERS = 2  # enough to drive the parallel path; small to stay light on memory


# --- state types (module-level so ProcessPoolExecutor can pickle them) --------------------------


@dataclass(frozen=True)
class Pair:
    a: int
    b: int


@dataclass(frozen=True)
class Boxed:
    """A state carrying a list field — not hashable, so it needs a ``key`` to be checked."""

    seq: tuple[int, ...]
    tag: list[str]

    __hash__ = None  # type: ignore[assignment]  # explicitly unhashable, like a pydantic model


# --- models -------------------------------------------------------------------------------------


def line_model(n: int, *, bad: int | None = None) -> Model[int]:
    """0..n with a single increment. With ``bad`` set, the invariant ``value != bad`` breaks at depth bad."""
    inc: Action[int] = Action("inc", enabled=lambda s: s < n, apply=lambda s: s + 1)
    invariants: dict[str, Invariant[int]] = {} if bad is None else {"not-bad": lambda s: s != bad}
    return Model(init=0, actions=[inc], invariants=invariants)


def deadlock_model() -> Model[int]:
    """Climbs 0->1->2->3 then stops with no action and is not terminal: a deadlock at depth 3."""
    inc: Action[int] = Action("inc", enabled=lambda s: s < 3, apply=lambda s: s + 1)
    return Model(init=0, actions=[inc])


def pair_model(n: int) -> Model[Pair]:
    inc_a: Action[Pair] = Action(
        "inc_a", enabled=lambda p: p.a < n, apply=lambda p: Pair(p.a + 1, p.b)
    )
    inc_b: Action[Pair] = Action(
        "inc_b", enabled=lambda p: p.b < n, apply=lambda p: Pair(p.a, p.b + 1)
    )
    return Model(init=Pair(0, 0), actions=[inc_a, inc_b])


def _sort_pair(p: Pair) -> Pair:
    lo, hi = sorted((p.a, p.b))
    return Pair(lo, hi)


def edge_model(n: int) -> Model[int]:
    """0..n with an edge-invariant that forbids the transition INTO 4 ('never step onto 4')."""
    inc: Action[int] = Action("inc", enabled=lambda s: s < n, apply=lambda s: s + 1)
    no_4: EdgeInvariant[int] = lambda s, a, t: t != 4  # noqa: E731
    return Model(init=0, actions=[inc], edge_invariants={"no-4": no_4})


def boxed_model(n: int) -> Model[Boxed]:
    """Unhashable states (list field); checked via a ``key`` that losslessly encodes the state."""
    inc: Action[Boxed] = Action(
        "inc",
        enabled=lambda b: len(b.seq) < n,
        apply=lambda b: Boxed(seq=(*b.seq, len(b.seq)), tag=[*b.tag, "x"]),
    )
    return Model(init=Boxed(seq=(), tag=[]), actions=[inc])


def _boxed_key(b: Boxed) -> tuple[tuple[int, ...], tuple[str, ...]]:
    return (b.seq, tuple(b.tag))


# --- parallel == serial -------------------------------------------------------------------------


def test_ok_matches_serial() -> None:
    model = line_model(50)
    assert check(model, workers=WORKERS) == check(model)


def test_invariant_violation_matches_serial() -> None:
    model = line_model(50, bad=7)
    par = check(model, workers=WORKERS)
    assert par == check(model)
    assert not par.ok
    assert par.kind == "invariant"
    assert par.action_names == ("inc",) * 7  # shortest path 0 -> 7


def test_deadlock_matches_serial() -> None:
    model = deadlock_model()
    par = check(model, workers=WORKERS)
    assert par == check(model)
    assert par.kind == "deadlock"
    assert par.witness == 3


def test_edge_invariant_matches_serial() -> None:
    model = edge_model(10)
    par = check(model, workers=WORKERS)
    assert par == check(model)
    assert par.kind == "edge-invariant"


def test_symmetry_matches_serial() -> None:
    model = pair_model(12)  # 13*13 = 169 states plain; ~half under the sort symmetry
    plain = check(model, workers=WORKERS)
    assert plain == check(model)
    sym_par = check(model, workers=WORKERS, canonicalize=_sort_pair)
    sym_ser = check(model, canonicalize=_sort_pair)
    assert sym_par == sym_ser
    assert sym_par.states_explored < plain.states_explored  # symmetry collapsed the space


def test_key_for_unhashable_state_matches_serial() -> None:
    model = boxed_model(20)
    assert check(model, workers=WORKERS, key=_boxed_key) == check(model, key=_boxed_key)


def test_workers_one_is_serial() -> None:
    model = line_model(30, bad=5)
    assert check(model, workers=1) == check(model)


def test_states_explored_matches_on_larger_space() -> None:
    model = pair_model(20)  # 441 states, several per level — exercises multi-state levels
    par = check(model, workers=WORKERS)
    ser = check(model)
    assert par.states_explored == ser.states_explored == 441
    assert par == ser
