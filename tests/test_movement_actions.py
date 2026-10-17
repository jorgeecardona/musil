"""The movement-table bridge (#24, part 1): build ledger actions straight from an edge-labelled
``label -> {(src, dst)}`` allowed-endpoints map, the shape a Petri-net-style ledger actually has."""

from __future__ import annotations

from dataclasses import dataclass

from musil import Model, check, explore
from musil.fsm import declared_accounts, endpoints_of, movement_actions

# A tiny coffee-roast ledger table: an event kind -> the (source, destination) account pairs it may
# move quantity between. "roast" splits — it may move green to roasted OR to loss — so one label maps
# to two endpoint pairs, which is exactly what `Table` cannot express.
TABLE: dict[str, set[tuple[str, str]]] = {
    "roast": {("green.loose", "roasted"), ("green.loose", "loss")},
    "grind": {("roasted", "ground")},
}

# State: account balances as a sorted tuple of (account, amount) pairs, so the state stays hashable.
type Balances = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Ledger:
    accounts: Balances


def bal(accounts: Balances, acct: str) -> int:
    return dict(accounts).get(acct, 0)


def move_one(accounts: Balances, src: str, dst: str) -> Balances:
    """Move one unit from ``src`` to ``dst`` — the caller-supplied arithmetic part 1 leaves open."""
    d = dict(accounts)
    d[src] = d.get(src, 0) - 1
    d[dst] = d.get(dst, 0) + 1
    return tuple(sorted(d.items()))


def ledger(**kw: int) -> Ledger:
    return Ledger(tuple(sorted(kw.items())))


def _move(s: Ledger, _label: str, src: str, dst: str) -> Ledger:
    return Ledger(move_one(s.accounts, src, dst))


def _has_balance(s: Ledger, _label: str, src: str, _dst: str) -> bool:
    return bal(s.accounts, src) > 0


def test_one_action_per_endpoint_pair() -> None:
    actions = movement_actions(TABLE, move=_move)
    names = {a.name for a in actions}
    assert names == {
        "roast:green.loose->roasted",
        "roast:green.loose->loss",
        "grind:roasted->ground",
    }


def test_movement_fires_and_moves_the_quantity() -> None:
    actions = movement_actions(TABLE, move=_move, enabled=_has_balance)
    roast_to_roasted = next(a for a in actions if a.name == "roast:green.loose->roasted")
    start = ledger(**{"green.loose": 2})
    assert roast_to_roasted.enabled(start)
    moved = roast_to_roasted.apply(start)
    assert bal(moved.accounts, "green.loose") == 1
    assert bal(moved.accounts, "roasted") == 1


def test_enabled_guard_prevents_overdraw() -> None:
    actions = movement_actions(TABLE, move=_move, enabled=_has_balance)
    grind = next(a for a in actions if a.name == "grind:roasted->ground")
    # no roasted yet -> the guard disables the movement, so roasted can never go negative
    assert not grind.enabled(ledger(**{"green.loose": 2}))


def test_declared_accounts_names_every_endpoint() -> None:
    assert declared_accounts(TABLE) == {"green.loose", "roasted", "loss", "ground"}


def test_endpoints_of_is_what_a_guard_checks() -> None:
    assert endpoints_of(TABLE, "roast") == frozenset(
        {("green.loose", "roasted"), ("green.loose", "loss")}
    )
    assert endpoints_of(TABLE, "grind") == frozenset({("roasted", "ground")})
    assert endpoints_of(TABLE, "unknown") == frozenset()


def test_model_from_table_conserves_mass_and_never_drifts() -> None:
    # 2 units of green, nothing else. Mass is conserved across every movement (nothing created or
    # destroyed, only relocated), and no balance ever goes negative.
    start = ledger(**{"green.loose": 2})
    total = 2

    model: Model[Ledger] = Model(
        init=start,
        actions=movement_actions(TABLE, move=_move, enabled=_has_balance),
        invariants={
            "mass-conserved": lambda s: sum(amt for _a, amt in s.accounts) == total,
            "no-negative-balance": lambda s: all(amt >= 0 for _a, amt in s.accounts),
        },
        # terminal: no green left to roast and nothing roasted left to grind -> a legitimate rest state
        terminal=lambda s: bal(s.accounts, "green.loose") == 0 and bal(s.accounts, "roasted") == 0,
    )
    result = check(model)
    assert result.ok

    # zero-drift: every edge the model ever takes is a declared (label, src, dst) from the table —
    # the builder cannot produce a movement the allowed-endpoints map does not sanction.
    declared_names = {f"{label}:{src}->{dst}" for label, eps in TABLE.items() for src, dst in eps}
    graph = explore(model)
    taken = {name for edges in graph.edges.values() for name, _nxt in edges}
    assert taken <= declared_names
