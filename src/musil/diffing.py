"""``diff`` — the behavioral delta between two model versions.

When a model is refactored (say, changing how actions are enumerated) the author wants to know behaviour
was preserved: the same reachable states, the same transitions, the same invariant outcomes. ``diff``
explores both models and reports exactly that delta over the two reachable graphs, so a refactor is
reviewable as "the reachable states and their validity are unchanged" rather than a leap of faith
([issue #14](https://gitlab.com/jorgeecardona/musil/-/work_items/14)).

States must be HASHABLE (``diff`` runs ``explore`` on both, which keys the graph by state); pass the same
``canonicalize`` to compare two models modulo the same symmetry.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from musil.core import Invariant, Model, explore


def _holds[S: Hashable](inv: Invariant[S], state: S) -> bool:
    """Whether ``inv`` holds at ``state`` (``check``'s semantics: a string return or falsy is a violation)."""
    verdict = inv(state)
    return not (isinstance(verdict, str) or not verdict)


@dataclass(frozen=True, slots=True)
class ModelDiff[S: Hashable]:
    """The behavioral delta between model A and model B over their reachable graphs.

    - ``states_only_in_a`` / ``states_only_in_b``: reachable in one but not the other.
    - ``transitions_only_in_a`` / ``transitions_only_in_b``: labelled edges ``(from, action, to)`` present
      in one but not the other.
    - ``invariant_changes``: over states reachable in BOTH and invariant names defined in BOTH, the
      ``(state, invariant, holds_in_a, holds_in_b)`` where the outcome flipped.

    ``equivalent`` is True when all four are empty — same reachable states, same transitions, same
    invariant outcomes on the shared states."""

    states_only_in_a: tuple[S, ...]
    states_only_in_b: tuple[S, ...]
    transitions_only_in_a: tuple[tuple[S, str, S], ...]
    transitions_only_in_b: tuple[tuple[S, str, S], ...]
    invariant_changes: tuple[tuple[S, str, bool, bool], ...]

    @property
    def equivalent(self) -> bool:
        return not (
            self.states_only_in_a
            or self.states_only_in_b
            or self.transitions_only_in_a
            or self.transitions_only_in_b
            or self.invariant_changes
        )

    def __str__(self) -> str:
        if self.equivalent:
            return "MODELS EQUIVALENT — same reachable states, transitions, and invariant outcomes"
        lines = ["MODEL DIFF:"]
        if self.states_only_in_a:
            lines.append(f"  {len(self.states_only_in_a)} state(s) only in A")
        if self.states_only_in_b:
            lines.append(f"  {len(self.states_only_in_b)} state(s) only in B")
        if self.transitions_only_in_a:
            lines.append(f"  {len(self.transitions_only_in_a)} transition(s) only in A")
        if self.transitions_only_in_b:
            lines.append(f"  {len(self.transitions_only_in_b)} transition(s) only in B")
        if self.invariant_changes:
            lines.append(f"  {len(self.invariant_changes)} invariant-outcome change(s) on shared states")
        return "\n".join(lines)


def diff[S: Hashable](
    model_a: Model[S],
    model_b: Model[S],
    *,
    canonicalize: Callable[[S], S] | None = None,
    max_states: int = 1_000_000,
) -> ModelDiff[S]:
    """Explore ``model_a`` and ``model_b`` and return their behavioral :class:`ModelDiff` (see there).
    ``canonicalize`` is applied to both (compare modulo the same symmetry); ``max_states`` caps each
    exploration. Reads only the reachable graphs, so it is O(states + transitions)."""
    ga = explore(model_a, max_states=max_states, canonicalize=canonicalize)
    gb = explore(model_b, max_states=max_states, canonicalize=canonicalize)
    in_a, in_b = set(ga.states), set(gb.states)

    edges_a = {(s, action, t) for s in ga.states for action, t in ga.edges.get(s, ())}
    edges_b = {(s, action, t) for s in gb.states for action, t in gb.edges.get(s, ())}

    shared_invariants = sorted(set(model_a.invariants) & set(model_b.invariants))
    invariant_changes: list[tuple[S, str, bool, bool]] = []
    for s in ga.states:
        if s not in in_b:
            continue
        for name in shared_invariants:
            holds_a = _holds(model_a.invariants[name], s)
            holds_b = _holds(model_b.invariants[name], s)
            if holds_a != holds_b:
                invariant_changes.append((s, name, holds_a, holds_b))

    return ModelDiff(
        states_only_in_a=tuple(s for s in ga.states if s not in in_b),
        states_only_in_b=tuple(s for s in gb.states if s not in in_a),
        transitions_only_in_a=tuple(e for s in ga.states for e in ((s, a, t) for a, t in ga.edges.get(s, ())) if e not in edges_b),
        transitions_only_in_b=tuple(e for s in gb.states for e in ((s, a, t) for a, t in gb.edges.get(s, ())) if e not in edges_a),
        invariant_changes=tuple(invariant_changes),
    )
