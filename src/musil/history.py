"""``with_last_action`` — put the action that produced a state INTO the state, so a temporal property can
name which action was taken.

A plain musil state says WHERE the system is, not HOW it got there. Some properties are about the action
sequence: "every ``request`` is eventually followed by a ``respond``", "``commit`` is never immediately
undone by ``rollback``". A state-only predicate cannot say "``request`` was just taken", and an edge invariant
(``core.EdgeInvariant``) can only make a SAFETY claim about a single step, not a liveness claim across a run.

``with_last_action(model)`` augments the model so each state becomes ``LastAction(state, action)`` — the
original state plus the name of the action that produced it (``None`` at an initial state). "which action was
taken" is now ordinary state data, so ``check_ltl`` and ``check_liveness`` express action-sequence properties
directly: ``G(action_taken('request') -> F action_taken('respond'))``. The transform lifts every field of the
model faithfully, so the augmented model is checked by exactly the same engines. Pure stdlib.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Any

from musil.core import Action, EdgeInvariant, Invariant, Model

__all__ = [
    "LastAction",
    "action_taken",
    "with_last_action",
]


@dataclass(frozen=True, slots=True)
class LastAction[S: Hashable]:
    """A state paired with the name of the action that produced it (``None`` at an initial state). The
    element type of ``with_last_action(model)``, so a property can name WHICH action was taken."""

    state: S
    action: str | None


def _lift_action[S: Hashable](a: Action[S]) -> Action[LastAction[S]]:
    """Lift one action to the augmented state space: same guard on the underlying state, and on firing it
    records its own name as the new ``last action``. Keeps the ``name`` and ``fair`` tag unchanged."""
    return Action(
        a.name,
        enabled=lambda la: a.enabled(la.state),
        apply=lambda la: LastAction(a.apply(la.state), a.name),
        fair=a.fair,
    )


def action_taken(name: str) -> Callable[[LastAction[Any]], bool]:
    """The predicate "the last action taken was ``name``", for building an ``Atom`` / invariant over a
    ``with_last_action`` model. False at an initial state (whose ``action`` is ``None``)."""
    return lambda la: la.action == name


def with_last_action[S: Hashable](model: Model[S]) -> Model[LastAction[S]]:
    """Augment ``model`` so each state carries the action that produced it (``LastAction`` = original state +
    last action name). "Which action was taken" becomes STATE data, so ``check_ltl`` / ``check_liveness`` can
    express properties over the ACTION SEQUENCE — e.g. "every ``request`` is eventually followed by a
    ``respond``" as ``G(action_taken('request') -> F action_taken('respond'))`` — which a state-only property
    cannot say and a safety-only edge invariant cannot make a liveness claim about.

    Every field is lifted faithfully: initial states get ``action=None``; each action keeps its ``name`` and
    ``fair`` tag and records itself on apply; ``invariants`` / ``terminal`` / ``edge_invariants`` / ``footprint``
    read the underlying ``.state``; ``actions_fn`` is lifted per state. The reachable space grows only by
    distinguishing states reached by different actions (a state reachable by two actions becomes two
    ``LastAction`` states). Counterexample traces are over ``LastAction`` — read ``.state`` and ``.action``.
    Use ``action_taken(name)`` for the "the last action was ``name``" predicate."""
    afn = model.actions_fn
    lifted_afn: Callable[[LastAction[S]], Iterable[Action[LastAction[S]]]] | None = (
        None if afn is None else (lambda la, _afn=afn: [_lift_action(a) for a in _afn(la.state)])
    )
    fp = model.footprint
    lifted_fp: Callable[[LastAction[S]], Hashable] | None = (
        None if fp is None else (lambda la, _fp=fp: _fp(la.state))
    )
    lifted_invariants: dict[str, Invariant[LastAction[S]]] = {
        name: (lambda la, _inv=inv: _inv(la.state)) for name, inv in model.invariants.items()
    }
    lifted_edges: dict[str, EdgeInvariant[LastAction[S]]] = {
        name: (lambda b, aname, a, _e=e: _e(b.state, aname, a.state))
        for name, e in model.edge_invariants.items()
    }
    term = model.terminal
    return Model(
        init=[LastAction(s, None) for s in model.initial_states()],
        actions=[_lift_action(a) for a in model.actions],
        invariants=lifted_invariants,
        terminal=lambda la: term(la.state),
        actions_fn=lifted_afn,
        footprint=lifted_fp,
        edge_invariants=lifted_edges,
    )
