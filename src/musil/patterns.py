"""``musil.patterns`` — the Dwyer/Corbett specification patterns as one-call helpers.

These helpers name the well-known patterns so a team picks the pattern instead of encoding the temporal
logic ([issue #16](https://gitlab.com/jorgeecardona/musil/-/work_items/16)):

- ``always(p)``    — universality: ``p`` holds in every reachable state (safety, via ``check``).
- ``absent(p)``    — absence: ``p`` holds in no reachable state (safety, via ``check``).
- ``eventually(p)``— existence: ``<>p``, every run reaches ``p`` (liveness).
- ``recurs(p)``    — recurrence: ``[]<>p``, every run reaches ``p`` infinitely often (liveness).
- ``responds(trigger, response)`` — response: ``[](trigger -> <>response)`` (liveness, leads-to).

The three LIVENESS patterns are SUGAR over ``check_ltl``: each builds the corresponding ``Eventually`` /
``Always(Eventually(...))`` / ``Always(Implies(...))`` formula and calls ``check_ltl``, which owns the one
reduction of the temporal fragment onto ``check_liveness``. So the lowering lives in a single place (fix or
extend it there and every pattern follows), and a pattern is by construction the same verdict as its LTL
formula (pinned in the corpus). The two SAFETY patterns stay direct ``check`` calls: ``G(state)`` is just an
invariant, and they expose ``canonicalize`` / ``key`` that the safety reduction inside ``check_ltl`` does
not forward, so routing them through it would drop those options for no gain.

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
from musil.liveness import LivenessResult
from musil.ltl import Always, Atom, Eventually, Implies, check_ltl


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
    fair: Iterable[str] | None = None,
    fair_strong: Iterable[str] | None = None,
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Existence: ``<>p`` — every run from an initial state eventually reaches a ``p``-state. Sugar for
    ``check_ltl(model, Eventually(p))``; ``fair``/``fair_strong`` prune cycles a fair scheduler would break."""
    result = check_ltl(model, Eventually(Atom(name, p)), name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
    assert isinstance(result, LivenessResult)  # F(state) always reduces to check_liveness
    return result


def recurs[S: Hashable](
    model: Model[S],
    p: Callable[[S], bool],
    *,
    name: str = "P",
    fair: Iterable[str] | None = None,
    fair_strong: Iterable[str] | None = None,
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Recurrence: ``[]<>p`` — every run reaches ``p`` infinitely often (past any point, ``p`` recurs).
    Sugar for ``check_ltl(model, Always(Eventually(p)))``."""
    result = check_ltl(
        model, Always(Eventually(Atom(name, p))), name=name, fair=fair, fair_strong=fair_strong, max_states=max_states
    )
    assert isinstance(result, LivenessResult)  # G F(state) always reduces to check_liveness(everywhere=True)
    return result


def responds[S: Hashable](
    model: Model[S],
    trigger: Callable[[S], bool],
    response: Callable[[S], bool],
    *,
    name: str = "response",
    fair: Iterable[str] | None = None,
    fair_strong: Iterable[str] | None = None,
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Response: ``[](trigger -> <>response)`` — whenever ``trigger`` holds, ``response`` eventually
    follows. The untimed "nothing gets stuck" property. Sugar for
    ``check_ltl(model, Always(Implies(trigger, Eventually(response))))``."""
    formula = Always(Implies(Atom("trigger", trigger), Eventually(Atom(name, response))))
    result = check_ltl(model, formula, name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
    assert isinstance(result, LivenessResult)  # G(a -> F b) always reduces to check_liveness(leadsto_from=a)
    return result
