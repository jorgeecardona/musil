"""Building the ``canonicalize`` that ``check``/``explore`` take -- symmetry reduction you can derive
rather than hand-write.

``check(model, canonicalize=...)`` has always accepted a symmetry reduction, and
``symmetry_reduction_sound`` has always been able to *grade* one. What was missing is the step
between: turning "these N components are interchangeable" into the function. Hand-writing it is
where the mistakes live, and an unsound canonicalizer silently drops reachable states -- a checker
returning green for a question nobody asked.

Two constructions, and which one is correct depends on one question: **does anything else in the
state name a component?**

- ``canonical_by_sorting`` -- the components are anonymous. Their slices are sorted into a canonical
  order. O(N log N), so it is the one that scales, and the one to reach for by default. Sound only
  while no *other* field refers to a component by position or id: sorting the slices destroys that
  correspondence, and the state that said "worker 2 holds the lock" now says something else.
- ``canonical_by_permutations`` -- something does name a component (a leader, an owner, a route id in
  a message). The whole state is relabelled under each permutation of the identities and the smallest
  result wins, so every reference moves with the component it names. Correct where sorting is not, and
  factorial: usable for a handful of identities, not for 24.

Both still have to pass ``symmetry_reduction_sound`` on a small instance before being trusted on a
large one -- that gate is the point, and neither construction removes the obligation. The sorting
case is exactly where it earns its keep: a model that grows a ``leader`` field next year makes a
previously-sound sort unsound, and nothing about the sort itself changes to say so."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from itertools import permutations
from math import factorial
from typing import Any

# A stable total order for picking an orbit's representative. Any fixed one is canonical; repr is
# used because model states are arbitrary hashable values and need not be comparable with <.
type Order[S] = Callable[[S], Any]


def canonical_by_sorting[S: Hashable, T](
    *,
    get: Callable[[S], Sequence[T]],
    put: Callable[[S, tuple[T, ...]], S],
    key: Callable[[T], Any] | None = None,
) -> Callable[[S], S]:
    """Canonicalize by sorting the interchangeable components' slices into a fixed order.

    ``get(state)`` reads the per-component slices (one entry per component, in component order) and
    ``put(state, slices)`` writes a reordered tuple back -- the same accessor pair the channel kit
    uses. ``key`` orders slices that are not comparable with ``<`` (a frozen dataclass per component,
    say); without it the slices are sorted directly.

    Collapses the N! orderings of N anonymous components into one representative, so a space that was
    ``V ** N`` becomes the multisets of size N over V. For 5 components over 3 values: 243 states
    down to 21.

    SOUND ONLY IF nothing outside these slices names a component. A ``leader: int`` field indexing
    into them, an id inside a message, a per-component key elsewhere in the state -- any of those and
    sorting breaks the reference while leaving the state well-formed, which is the quiet kind of
    wrong. Use ``canonical_by_permutations`` there, and either way run ``symmetry_reduction_sound``
    on a small instance first."""

    def canonicalize(state: S) -> S:
        return put(state, tuple(sorted(get(state), key=key)))  # type: ignore[arg-type, type-var]

    return canonicalize


def canonical_by_permutations[S: Hashable, I](
    identities: Sequence[I],
    relabel: Callable[[S, Mapping[I, I]], S],
    *,
    order: Order[S] = repr,
    max_permutations: int = 5_040,
) -> Callable[[S], S]:
    """Canonicalize by taking the smallest state in its orbit under every permutation of
    ``identities`` -- the general construction, for when the identities are referenced.

    ``relabel(state, mapping)`` applies one permutation to the WHOLE state: every place an identity
    appears must be rewritten, not just the per-component slices. Missing one is precisely the bug
    this construction exists to avoid, and it shows up as ``symmetry_reduction_sound`` returning
    False rather than as a wrong answer.

    ``order`` is the total order the minimum is taken under; any fixed one yields a canonical
    representative, and the default ``repr`` works for arbitrary states without requiring ``<``. It
    must be stable for the duration of a check -- true for the frozen dataclasses states are normally
    written as. (Ordering by ``repr`` of a ``frozenset`` field is stable within a process but varies
    between runs under hash randomization: still canonical, just not reproducible across runs.)

    The orbit has ``len(identities)!`` elements and all of them are built for every state, so this is
    for a handful of identities. ``max_permutations`` (5040 = 7!) makes that a loud error instead of a
    hang; raising it is a decision, not a default. For many anonymous components, ``canonical_by_sorting``
    is the construction that scales."""
    n = len(identities)
    if factorial(n) > max_permutations:
        raise ValueError(
            f"{n} identities means {factorial(n)} permutations per state, over the "
            f"max_permutations={max_permutations} cap. Sorting the per-component slices with "
            "canonical_by_sorting is the construction that scales; raise the cap only if the "
            "identities really are referenced elsewhere and N is small."
        )
    perms = tuple(
        dict(zip(identities, p, strict=True)) for p in permutations(identities)
    )

    def canonicalize(state: S) -> S:
        return min((relabel(state, p) for p in perms), key=order)

    return canonicalize
