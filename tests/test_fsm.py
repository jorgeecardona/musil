"""The transition-table bridge: build a model straight from an ALLOWED-style map (zero drift)."""

from __future__ import annotations

from dataclasses import dataclass

from musil import (
    Model,
    check,
    declared_states,
    status_field_actions,
    terminal_states,
    transition_actions,
)

# A tiny ALLOWED-style table with one absorbing sink ("deleted").
TABLE: dict[str, set[str]] = {
    "pending": {"active", "failed"},
    "active": {"deleting", "failed"},
    "failed": {"active", "deleting"},
    "deleting": {"deleted", "failed"},
    "deleted": set(),
}


@dataclass(frozen=True)
class Thing:
    status: str


def test_declared_and_terminal_states() -> None:
    assert declared_states(TABLE) == {"pending", "active", "failed", "deleting", "deleted"}
    assert terminal_states(TABLE) == {"deleted"}


def test_transition_actions_cover_every_edge() -> None:
    actions = transition_actions(
        TABLE, get=lambda t: t.status, with_status=lambda t, s: Thing(s)
    )
    names = {a.name for a in actions}
    expected = {f"{src}->{dst}" for src, dsts in TABLE.items() for dst in dsts}
    assert names == expected
    # an action only fires from its source state
    pending_to_active = next(a for a in actions if a.name == "pending->active")
    assert pending_to_active.enabled(Thing("pending"))
    assert not pending_to_active.enabled(Thing("active"))
    assert pending_to_active.apply(Thing("pending")) == Thing("active")


def test_model_built_from_table_is_reachable_and_sound() -> None:
    model = Model(
        init=Thing("pending"),
        actions=status_field_actions(TABLE),  # reads/replaces the `status` field
        invariants={"known": lambda t: t.status in declared_states(TABLE)},
        terminal=lambda t: t.status in terminal_states(TABLE),
    )
    result = check(model)
    assert result.ok
    assert result.states_explored == len(declared_states(TABLE))  # every state reachable, no dead ends


def test_table_with_unreachable_state_leaves_it_unexplored() -> None:
    # 'orphan' is declared as a target of nothing reachable from pending
    table = {"pending": {"active"}, "active": set(), "orphan": {"active"}}
    model = Model(
        init=Thing("pending"),
        actions=status_field_actions(table),
        terminal=lambda t: t.status in terminal_states(table),
    )
    result = check(model)
    assert result.ok
    # only pending + active reachable; orphan never visited
    assert result.states_explored == 2
