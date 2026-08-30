"""Partial-order reduction (POR) — explore only an *ample set* of actions per state, plus the soundness
gate that makes any ample choice safe to trust.

musil explores every interleaving of concurrent actions, which is what finds races and also what blows the
state space up (N independent actions give N! orderings, most redundant). POR fires only a sufficient
subset — an *ample set* — at each state. An unsound ample set silently drops reachable states and the
violations only they reach, which is strictly worse than being slow, so POR ships with ``por_sound``: the
gate that validates an ample function against the full exploration before it is trusted (the same
discipline as ``symmetry_reduction_sound`` / ``footprint_sound``). See ``REDUCTION_NOTES.md``.

This layer provides the MECHANISM (``explore_por`` takes a caller-supplied ``ample``) and the GATE
(``por_sound``); the automatic ample-set computation from the independence relation lands on top, validated
by the gate. ``independent`` is the concrete per-state independence test the computation rests on.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from musil.core import (
    Action,
    Graph,
    Invariant,
    Model,
    actions_source,
    explore,
    reachable_violations,
)

# An ample function: given a state and its enabled actions, return the subset to fire. MUST return a
# subset of the enabled actions; SOUNDNESS (that firing only these preserves the properties of interest)
# is the caller's obligation, validated by por_sound.
type Ample[S] = Callable[[S, tuple[Action[S], ...]], Iterable[Action[S]]]


def independent[S: Hashable](a: Action[S], b: Action[S], state: S) -> bool:
    """Whether actions ``a`` and ``b`` are INDEPENDENT at ``state``: both enabled there, each still enabled
    after the other fires (neither disables the other), and they COMMUTE
    (``apply(a, apply(b, s)) == apply(b, apply(a, s))``). musil can test this concretely per state because
    ``enabled``/``apply`` are pure functions — an advantage over tools that need a static independence
    relation. (Independence is defined only for co-enabled actions; returns False otherwise.)"""
    if not (a.enabled(state) and b.enabled(state)):
        return False
    after_a = a.apply(state)
    after_b = b.apply(state)
    if not (b.enabled(after_a) and a.enabled(after_b)):
        return False
    return a.apply(after_b) == b.apply(after_a)


def explore_por[S: Hashable](
    model: Model[S],
    *,
    ample: Ample[S],
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
) -> Graph[S]:
    """Build the reachable graph firing only ``ample(state, enabled_actions)`` at each state instead of
    every enabled action. ``ample`` MUST return a subset of the enabled actions. SOUNDNESS is the caller's
    obligation — validate the ``ample`` with ``por_sound`` before trusting the reduced graph. With
    ``ample = lambda state, enabled: enabled`` this is exactly ``explore``."""
    source = actions_source(model)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    seen: dict[S, list[tuple[str, S]]] = {}
    frontier: list[S] = []
    for s0 in model.initial_states():
        s = canon(s0)
        if s not in seen:
            seen[s] = []
            frontier.append(s)
    head = 0
    truncated = False
    while head < len(frontier):
        state = frontier[head]
        head += 1
        enabled = tuple(a for a in source(state) if a.enabled(state))
        out: list[tuple[str, S]] = []
        for action in ample(state, enabled):
            nxt = canon(action.apply(state))
            out.append((action.name, nxt))
            if nxt not in seen:
                seen[nxt] = []
                frontier.append(nxt)
                if len(seen) >= max_states:
                    truncated = True
                    break
        seen[state] = out
        if truncated:
            break
    return Graph(
        initial=tuple(canon(s) for s in model.initial_states()),
        states=tuple(seen),
        edges={s: tuple(o) for s, o in seen.items()},
        truncated=truncated,
    )


def _violated[S: Hashable](inv: Invariant[S], state: S) -> bool:
    verdict = inv(state)
    return isinstance(verdict, str) or not verdict


def por_sound[S: Hashable](model: Model[S], ample: Ample[S], *, max_states: int = 1_000_000) -> bool:
    """Validate a POR ``ample`` for ``model`` on a (bounded) instance — the gate that should pass before
    ``explore_por(..., ample=...)`` (and any check built on it) is trusted.

    It explores the model FULL and REDUCED and confirms two things:
    (1) the reduced reachable set is a SUBSET of the full one (POR must not invent states); and
    (2) the SAME set of invariants is violable in both — an ample set that drops the only path to a
        violation makes these disagree and returns False.

    This certifies preservation of SAFETY (invariant violability), which is what the standard ample-set
    conditions guarantee. Deadlock-freedom and liveness need the extra proviso (C3) and are NOT covered
    here — validate those separately. Returns False if either exploration truncated (inconclusive)."""
    full = explore(model, max_states=max_states)
    reduced = explore_por(model, ample=ample, max_states=max_states)
    if full.truncated or reduced.truncated:
        return False
    if not set(reduced.states) <= set(full.states):
        return False
    full_violated = {v.invariant for v in reachable_violations(model, max_states=max_states)}
    reduced_violated = {
        name for s in reduced.states for name, inv in model.invariants.items() if _violated(inv, s)
    }
    return full_violated == reduced_violated
