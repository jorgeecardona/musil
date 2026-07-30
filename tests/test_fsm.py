"""The transition-table bridge: build a model straight from an ALLOWED-style map (zero drift)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from musil import (
    Model,
    check,
    declared_states,
    explore,
    multi_status_field_actions,
    protocol_actions,
    protocol_operations,
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
    table: dict[str, set[str]] = {"pending": {"active"}, "active": set(), "orphan": {"active"}}
    model = Model(
        init=Thing("pending"),
        actions=status_field_actions(table),
        terminal=lambda t: t.status in terminal_states(table),
    )
    result = check(model)
    assert result.ok
    # only pending + active reachable; orphan never visited
    assert result.states_explored == 2


def test_multi_status_field_actions_drives_several_machines() -> None:
    # a state with two independent status fields, each its own table; the product is explored.
    @dataclass(frozen=True)
    class Pair:
        a: str = "pending"
        b: str = "pending"

    table_a: dict[str, set[str]] = {"pending": {"active"}, "active": set()}
    table_b: dict[str, set[str]] = {"pending": {"on", "off"}, "on": {"off"}, "off": {"on"}}
    actions = multi_status_field_actions({"a": table_a, "b": table_b})
    names = {act.name for act in actions}
    assert "a:pending->active" in names and "b:on->off" in names  # namespaced per field
    model = Model(init=Pair(), actions=actions,
                  invariants={"known": lambda s: s.a in declared_states(table_a)
                              and s.b in declared_states(table_b)})
    result = check(model)
    assert result.ok
    # |reachable a| * |reachable b| = 2 (pending,active) * 3 (pending,on,off) = 6
    assert result.states_explored == 6


# --- protocol tables: edges labelled by the operation, not just by the target ------------------


class Handshake(StrEnum):
    START = "start"
    OFFERED = "offered"
    OPEN = "open"
    CLOSED = "closed"


PROTOCOL: dict[Handshake, dict[str, Handshake | None]] = {
    Handshake.START: {"hello": Handshake.OFFERED, "log": None},
    Handshake.OFFERED: {"accept": Handshake.OPEN, "reject": Handshake.CLOSED, "log": None},
    Handshake.OPEN: {"send": None, "close": Handshake.CLOSED},
    Handshake.CLOSED: {},
}


def _protocol_model() -> Model[Handshake]:
    return Model(
        init=[Handshake.START],
        actions=protocol_actions(PROTOCOL, get=lambda s: s, with_state=lambda _s, t: t),
        terminal=lambda s: s is Handshake.CLOSED,
    )


def test_protocol_actions_build_one_action_per_moving_operation() -> None:
    names = {action.name for action in _protocol_model().actions}
    assert names == {
        "hello in start",
        "accept in offered",
        "reject in offered",
        "close in open",
    }, "operations that do not move must not become actions"


def test_a_protocol_table_drives_a_check() -> None:
    result = check(_protocol_model())
    assert result.ok, str(result)
    assert result.states_explored == len(Handshake)


def test_a_state_nothing_can_enter_is_visible_in_the_reachable_set() -> None:
    """The reason to check a transcribed specification at all: an unreachable state is a
    transcription error, and reading the table will not show it to you."""
    orphan = dict(PROTOCOL)
    orphan[Handshake.OFFERED] = {"log": None}  # nothing accepts or rejects any more
    model = Model(
        init=[Handshake.START],
        actions=protocol_actions(orphan, get=lambda s: s, with_state=lambda _s, t: t),
        terminal=lambda s: s in {Handshake.CLOSED, Handshake.OFFERED},
    )
    reached = set(explore(model).states)
    assert Handshake.OPEN not in reached
    assert Handshake.CLOSED not in reached


def test_protocol_operations_lists_what_a_guard_would_allow() -> None:
    """Including the ones that do not move -- a guard has to know about those too."""
    assert protocol_operations(PROTOCOL, Handshake.OPEN) == frozenset({"send", "close"})
    assert protocol_operations(PROTOCOL, Handshake.CLOSED) == frozenset()
