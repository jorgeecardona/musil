"""Build a model straight from a transition table — ``{from_state: {to_states}}`` — instead of
hand-writing one Action per edge. This is the zero-drift bridge: point it at the very table your
code enforces (e.g. a state machine's allowed-transitions map) and the model can never disagree
with the code, because it *is* the code's table. No separate spec file to keep in sync.

Generic over the state type: you supply ``get`` (read the status out of a state) and ``with_status``
(return a new state with the status replaced), so the table can drive any state shape — typically a
frozen dataclass with a ``status`` field plus whatever other variables your invariants need."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Set
from dataclasses import replace
from typing import Any

from musil.core import Action

# A transition table: from_state -> the set of states it may move to. Matches the shape of a typical
# `ALLOWED[entity]` map. Values may be any set/frozenset/collection of strings.
type Table = Mapping[str, Set[str]]


def transition_actions[S: Hashable](
    table: Table,
    *,
    get: Callable[[S], str],
    with_status: Callable[[S, str], S],
    name: Callable[[str, str], str] = lambda src, dst: f"{src}->{dst}",
) -> list[Action[S]]:
    """One Action per declared ``src -> dst`` edge. ``get`` reads the current status from a state;
    ``with_status`` returns a new state with the status set to ``dst`` (states are immutable)."""
    actions: list[Action[S]] = []
    for src, dsts in table.items():
        for dst in dsts:
            actions.append(
                Action(
                    name=name(src, dst),
                    # default-arg capture pins src/dst per loop iteration (avoid late-binding).
                    enabled=lambda s, _src=src: get(s) == _src,
                    apply=lambda s, _dst=dst: with_status(s, _dst),
                )
            )
    return actions


def status_field_actions(table: Table, *, field: str = "status") -> list[Action[Any]]:
    """Convenience for the common case: states are frozen dataclasses whose status lives in a single
    field (default ``status``). Builds actions that read/replace that field via dataclasses.replace."""
    return transition_actions(
        table,
        get=lambda s: getattr(s, field),
        with_status=lambda s, dst: replace(s, **{field: dst}),
    )


def declared_states(table: Table) -> set[str]:
    """Every state named in the table — sources (keys) plus every target."""
    return set(table) | {dst for dsts in table.values() for dst in dsts}


def terminal_states(table: Table) -> set[str]:
    """States with no outgoing transitions — absorbing sinks (a key mapped to an empty set, or a
    target that's never a source). Use to build a model's ``terminal`` predicate so a legitimate
    resting/sink state isn't reported as a deadlock."""
    return {s for s in declared_states(table) if not table.get(s)}
