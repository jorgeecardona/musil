"""``musil.patterns`` — the Dwyer/Corbett specification patterns as one-call helpers.

musil already has the primitives (``check`` for safety, ``check_liveness`` for ``<>P`` / ``[]<>P`` / the
response property), but the common temporal properties get hand-rolled each time, which is error-prone and
a barrier for non-specialists. These helpers name the well-known patterns and lower each onto an existing
check, so a team picks the pattern instead of encoding the temporal logic
([issue #16](https://gitlab.com/jorgeecardona/musil/-/work_items/16)):

- ``always(p)``    — universality: ``p`` holds in every reachable state (safety, via ``check``).
- ``absent(p)``    — absence: ``p`` holds in no reachable state (safety, via ``check``).
- ``eventually(p)``— existence: ``<>p``, every run reaches ``p`` (liveness, via ``check_liveness``).
- ``recurs(p)``    — recurrence: ``[]<>p``, every run reaches ``p`` infinitely often (liveness).
- ``responds(trigger, response)`` — response: ``[](trigger -> <>response)`` (liveness, leads-to).

Each returns whatever its underlying check returns (a ``Result`` for the safety patterns, a
``LivenessResult`` for the liveness ones); both satisfy the ``Verdict`` protocol (``.ok`` + ``__str__``),
so ``assert_ok`` works uniformly.

Scope: these are the GLOBAL-scope patterns. The scoped variants (after / between / until a delimiter) and
the precedence family (which need the state to carry history of what has happened) are deliberately not
here yet — see issue #16 for the plan.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import replace

from musil.core import Model, Result, check
from musil.liveness import LivenessResult, check_liveness


def always[S: Hashable](
    model: Model[S],
    p: Callable[[S], bool],
    *,
    name: str = "always",
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
) -> Result[S]:
    """Universality: ``p`` holds in EVERY reachable state. Lowers to ``check`` with ``p`` as the sole
    invariant; the ``Result`` carries the shortest trace to a state where ``p`` fails."""
    return check(replace(model, invariants={name: p}), max_states=max_states, canonicalize=canonicalize, key=key)


def absent[S: Hashable](
    model: Model[S],
    p: Callable[[S], bool],
    *,
    name: str = "absent",
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
) -> Result[S]:
    """Absence: ``p`` holds in NO reachable state. Lowers to ``check`` with ``not p`` as the invariant."""

    def never(state: S) -> bool:
        return not p(state)

    return check(replace(model, invariants={name: never}), max_states=max_states, canonicalize=canonicalize, key=key)


def eventually[S: Hashable](
    model: Model[S],
    p: Callable[[S], bool],
    *,
    name: str = "P",
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Existence: ``<>p`` — every run from an initial state eventually reaches a ``p``-state. Lowers to
    ``check_liveness``; ``fair``/``fair_strong`` prune cycles a fair scheduler would break."""
    return check_liveness(model, goal=p, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)


def recurs[S: Hashable](
    model: Model[S],
    p: Callable[[S], bool],
    *,
    name: str = "P",
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Recurrence: ``[]<>p`` — every run reaches ``p`` infinitely often (past any point, ``p`` recurs).
    Lowers to ``check_liveness(everywhere=True)``."""
    return check_liveness(
        model, goal=p, everywhere=True, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states
    )


def responds[S: Hashable](
    model: Model[S],
    trigger: Callable[[S], bool],
    response: Callable[[S], bool],
    *,
    name: str = "response",
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Response: ``[](trigger -> <>response)`` — whenever ``trigger`` holds, ``response`` eventually
    follows. The untimed "nothing gets stuck" property. Lowers to ``check_liveness(leadsto_from=trigger)``."""
    return check_liveness(
        model, goal=response, leadsto_from=trigger, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states
    )
