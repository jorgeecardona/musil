"""Deriving a `canonicalize` instead of hand-writing it: sorting for anonymous components,
permutations for identities something else refers to."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from math import comb

import pytest

from musil import (
    Action,
    Model,
    canonical_by_permutations,
    canonical_by_sorting,
    check,
    explore,
    symmetry_reduction_sound,
)

VALUES = 3  # each worker counts 0, 1, 2


@dataclass(frozen=True)
class Workers:
    """N interchangeable workers, nothing else. counts[i] is worker i's progress."""

    counts: tuple[int, ...]


def _workers(n: int) -> Model[Workers]:
    def step(i: int) -> Action[Workers]:
        return Action(
            f"w{i}:step",
            lambda s: s.counts[i] < VALUES - 1,
            lambda s: replace(s, counts=(*s.counts[:i], s.counts[i] + 1, *s.counts[i + 1 :])),
        )

    return Model(init=Workers((0,) * n), actions=[step(i) for i in range(n)])


def _sorted_workers() -> Callable[[Workers], Workers]:
    canon: Callable[[Workers], Workers] = canonical_by_sorting(
        get=lambda s: s.counts, put=lambda s, xs: replace(s, counts=xs)
    )
    return canon


@pytest.mark.parametrize("n", [3, 4, 5])
def test_sorting_collapses_the_orderings_and_passes_the_soundness_gate(n: int) -> None:
    model = _workers(n)
    full = explore(model).states
    reduced = explore(model, canonicalize=_sorted_workers()).states

    # every assignment of VALUES values to n workers, versus the multisets of the same size
    assert len(full) == VALUES**n
    assert len(reduced) == comb(n + VALUES - 1, n)
    assert all(list(s.counts) == sorted(s.counts) for s in reduced)

    # the saving and the soundness are one claim: a reduction that shrinks and lies is worthless
    assert symmetry_reduction_sound(model, _sorted_workers())


def test_the_saving_grows_with_the_number_of_components() -> None:
    ratios = [
        len(explore(_workers(n)).states) / len(explore(_workers(n), canonicalize=_sorted_workers()).states)
        for n in (3, 4, 5)
    ]
    assert ratios == sorted(ratios)
    assert ratios[-1] > ratios[0] * 2  # 2.7x at n=3 to 11.6x at n=5


def test_the_reduced_run_still_finds_the_violation() -> None:
    model = _workers(4)
    model.invariants = {"not-all-done": lambda s: not all(c == VALUES - 1 for c in s.counts)}
    full = check(model)
    reduced = check(model, canonicalize=_sorted_workers())
    assert not full.ok and not reduced.ok
    assert full.invariant == reduced.invariant == "not-all-done"


# --- when something names a component, sorting is the wrong construction -----------------------


@dataclass(frozen=True)
class Cluster:
    """The same workers, plus a leader that names one of them by index. Only the leader is allowed to
    reach the last value, so the reference is load-bearing: a canonicalizer that moves the counts and
    leaves `leader` behind describes a different cluster."""

    counts: tuple[int, ...]
    leader: int


def _cluster(n: int) -> Model[Cluster]:
    def step(i: int) -> Action[Cluster]:
        # non-leaders stop one short of the last value; the leader may finish
        return Action(
            f"w{i}:step",
            lambda s: s.counts[i] < (VALUES - 1 if i == s.leader else VALUES - 2),
            lambda s: replace(s, counts=(*s.counts[:i], s.counts[i] + 1, *s.counts[i + 1 :])),
        )

    def _capped(s: Cluster, i: int) -> int:
        return VALUES - 1 if i == s.leader else VALUES - 2

    return Model(
        init=Cluster((0,) * n, 0),
        actions=[step(i) for i in range(n)],
        # everyone has gone as far as they may: a legitimate sink, not a deadlock
        terminal=lambda s: all(c == _capped(s, i) for i, c in enumerate(s.counts)),
        invariants={
            "only-leader-finishes": lambda s: all(
                c < VALUES - 1 or i == s.leader for i, c in enumerate(s.counts)
            )
        },
    )


def _relabel(s: Cluster, perm: Mapping[int, int]) -> Cluster:
    counts = [0] * len(s.counts)
    for i, c in enumerate(s.counts):
        counts[perm[i]] = c
    return Cluster(tuple(counts), perm[s.leader])


def test_the_cluster_model_itself_is_clean() -> None:
    # the baseline the next two tests are measured against: nothing is wrong with this model
    assert check(_cluster(3)).ok


def test_sorting_is_unsound_once_a_field_names_a_component() -> None:
    # sorting the counts leaves `leader` pointing at whoever now sits at that index. The state stays
    # well-formed and starts violating an invariant the real model never violates -- a reduction that
    # invents a bug. The gate is what catches it.
    sort_counts: Callable[[Cluster], Cluster] = canonical_by_sorting(
        get=lambda s: s.counts, put=lambda s, xs: replace(s, counts=xs)
    )
    assert not symmetry_reduction_sound(_cluster(3), sort_counts)
    invented = check(_cluster(3), canonicalize=sort_counts)
    assert invented.kind == "invariant" and invented.invariant == "only-leader-finishes"


def test_permutations_relabel_the_reference_and_are_sound() -> None:
    model = _cluster(3)
    canon = canonical_by_permutations([0, 1, 2], _relabel)
    assert symmetry_reduction_sound(model, canon)
    assert check(model, canonicalize=canon).ok  # no invented violation
    assert len(explore(model, canonicalize=canon).states) < len(explore(model).states)


def test_a_relabel_that_forgets_the_reference_fails_the_gate() -> None:
    # exactly the mistake canonical_by_permutations exists to make visible: permute the slices but
    # leave the leader index alone. Same failure as sorting, reached a different way.
    def half_relabel(s: Cluster, perm: Mapping[int, int]) -> Cluster:
        counts = [0] * len(s.counts)
        for i, c in enumerate(s.counts):
            counts[perm[i]] = c
        return Cluster(tuple(counts), s.leader)  # leader not relabelled

    assert not symmetry_reduction_sound(_cluster(3), canonical_by_permutations([0, 1, 2], half_relabel))


def test_the_reduced_and_full_runs_agree_on_a_real_violation() -> None:
    model = _cluster(3)
    model.invariants = {"leader-idle": lambda s: s.counts[s.leader] == 0}  # false once it steps
    canon = canonical_by_permutations([0, 1, 2], _relabel)
    full = check(model)
    reduced = check(model, canonicalize=canon)
    assert not full.ok and not reduced.ok
    assert full.invariant == reduced.invariant == "leader-idle"


def test_too_many_identities_is_a_loud_error_not_a_hang() -> None:
    with pytest.raises(ValueError, match="canonical_by_sorting is the construction that scales"):
        canonical_by_permutations(list(range(8)), _relabel)


def test_the_cap_can_be_raised_deliberately() -> None:
    canon = canonical_by_permutations([0, 1, 2, 3], _relabel, max_permutations=24)
    assert canon(Cluster((1, 0, 0, 0), 0)) == canon(Cluster((0, 0, 0, 1), 3))
