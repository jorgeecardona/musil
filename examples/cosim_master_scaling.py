"""Co-simulation master over N interchangeable components: the state-space scaling curve, with and without
symmetry reduction. The named partial-order-reduction benchmark, run as a measurement (see
``src/musil/REDUCTION_NOTES.md`` for why POR itself stays deferred behind this curve).

THE MODEL (a generic stand-in, no product code). A co-simulation master algorithm (FMI-style) advances N
sub-components in lock-step: within one macro step each component takes up to ``k`` local micro-steps; when
all reach the boundary the master commits, or on a failure it ROLLS BACK every component to the macro-start
snapshot and retries. The per-component ``step`` actions are mutually INDEPENDENT (each touches only its own
slot), so musil explores every interleaving and the reachable set is ``(k+1) ** N`` -- the classic
concurrent blowup. The components are ANONYMOUS (interchangeable): nothing outside a component's own slice
names it, so the N! orderings are redundant.

THE LEVER. Because the components are interchangeable, ``canonical_by_sorting`` (sort the per-component
slices into a fixed order) is a SOUND symmetry reduction: it collapses each orbit of N! orderings to one
representative, so the space drops from ``(k+1) ** N`` to the multisets of size N over ``k+1`` values,
``C(N + k, N)`` -- polynomial in N, not exponential. This is the "interchangeable components in a composed
model" recipe: build the accessor pair over the per-component slices, hand it to ``canonical_by_sorting``,
and VALIDATE it with ``symmetry_reduction_sound`` on a small instance before trusting it on a large one.

Run: python examples/cosim_master_scaling.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import comb
from time import perf_counter

from musil import (
    Action,
    Model,
    canonical_by_sorting,
    check,
    symmetry_reduction_sound,
)


@dataclass(frozen=True)
class Master:
    """The master's state: ``steps[i]`` is component ``i``'s micro-step within the current macro step
    (0..k). The macro-start snapshot is the all-zero tuple; rollback restores it."""

    steps: tuple[int, ...]


def _step_action(i: int, k: int) -> Action[Master]:
    """Component ``i`` takes one local micro-step. Independent of every other component's step action:
    it reads and writes only slot ``i``."""

    def enabled(s: Master) -> bool:
        return s.steps[i] < k

    def apply(s: Master) -> Master:
        return replace(s, steps=(*s.steps[:i], s.steps[i] + 1, *s.steps[i + 1 :]))

    return Action(f"step{i}", enabled=enabled, apply=apply)


def _rollback_action(k: int) -> Action[Master]:
    """The master restores the macro-start snapshot (all components back to 0) after a partial advance --
    a step failure in the composed run. Adds interleavings (edges) but no new reachable states."""

    def enabled(s: Master) -> bool:
        return any(x > 0 for x in s.steps) and not all(x == k for x in s.steps)

    def apply(s: Master) -> Master:
        return replace(s, steps=tuple(0 for _ in s.steps))

    return Action("rollback", enabled=enabled, apply=apply)


def master_model(n: int, *, k: int = 3) -> Model[Master]:
    """A co-simulation master over ``n`` interchangeable components, each taking up to ``k`` micro-steps
    per macro step, with rollback. Terminal once every component reaches the macro boundary."""
    actions = [_step_action(i, k) for i in range(n)]
    actions.append(_rollback_action(k))
    return Model(
        init=Master(steps=tuple(0 for _ in range(n))),
        actions=actions,
        invariants={"within-bounds": lambda s: all(0 <= x <= k for x in s.steps)},  # trivially holds
        terminal=lambda s: all(x == k for x in s.steps),
    )


def by_sorting() -> Callable[[Master], Master]:
    """The interchangeable-components recipe: canonicalize by sorting the per-component slices. Here the
    slice IS the whole per-component datum (its step count), so the accessor pair is read/write of
    ``steps``. Sound because nothing outside ``steps`` names a component."""

    def get(s: Master) -> tuple[int, ...]:
        return s.steps

    def put(s: Master, xs: tuple[int, ...]) -> Master:
        return replace(s, steps=xs)

    return canonical_by_sorting(get=get, put=put)


def measure(n: int, *, k: int = 3) -> tuple[int, float, int, float]:
    """Return ``(states_full, seconds_full, states_reduced, seconds_reduced)`` for ``n`` components: a full
    ``check`` sweep vs the same check under the sorting symmetry."""
    model = master_model(n, k=k)
    canon = by_sorting()

    t0 = perf_counter()
    full = check(model)
    dt_full = perf_counter() - t0

    t0 = perf_counter()
    reduced = check(model, canonicalize=canon)
    dt_reduced = perf_counter() - t0

    return full.states_explored, dt_full, reduced.states_explored, dt_reduced


def main() -> None:
    k = 3
    print(f"Co-simulation master, k={k} micro-steps per component, with rollback.")
    print("Reachable states: full interleaving = (k+1)**n; under sorting symmetry = C(n+k, n).\n")
    print(f"{'n':>2} | {'full states':>12} {'full s':>9} | {'sym states':>11} {'sym s':>9} | {'shrink':>7}")
    print("-" * 66)
    for n in range(2, 6):
        canon = by_sorting()
        # trust, but verify: the recipe is only sound if this passes on the instance.
        assert symmetry_reduction_sound(master_model(n, k=k), canon), f"symmetry unsound at n={n}"
        s_full, t_full, s_sym, t_sym = measure(n, k=k)
        assert s_full == (k + 1) ** n, (n, s_full)
        assert s_sym == comb(n + k, n), (n, s_sym)
        print(
            f"{n:>2} | {s_full:>12,} {t_full:>9.4f} | {s_sym:>11,} {t_sym:>9.4f} | "
            f"{s_full / s_sym:>6.1f}x"
        )
    print(
        "\nReading: the full column is exponential in n; the symmetry column is polynomial. For anonymous\n"
        "interchangeable components, canonical_by_sorting is the documented lever -- POR is not needed to\n"
        "make this workload tractable. Validate every recipe with symmetry_reduction_sound before trusting it."
    )


if __name__ == "__main__":
    main()
