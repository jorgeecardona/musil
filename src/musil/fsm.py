"""Build a model straight from a transition table — ``{from_state: {to_states}}`` — instead of
hand-writing one Action per edge. This is the zero-drift bridge: point it at the very table your
code enforces (e.g. a state machine's allowed-transitions map) and the model can never disagree
with the code, because it *is* the code's table. No separate spec file to keep in sync.

Generic over the state type: you supply ``get`` (read the status out of a state) and ``with_status``
(return a new state with the status replaced), so the table can drive any state shape — typically a
frozen dataclass with a ``status`` field plus whatever other variables your invariants need."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Set
from dataclasses import replace
from typing import Any

from musil.core import Action, Model, explore

# A transition table: from_state -> the set of states it may move to. Matches the shape of a typical
# `ALLOWED[entity]` map. Values may be any set/frozenset/collection of strings.
type Table = Mapping[str, Set[str]]


def transition_actions[S: Hashable](
    table: Table,
    *,
    get: Callable[[S], str],
    with_status: Callable[[S, str], S],
    effect: Callable[[S, str, str], S] | None = None,
    also: Callable[[S], bool] | None = None,
    name: Callable[[str, str], str] = lambda src, dst: f"{src}->{dst}",
) -> list[Action[S]]:
    """One Action per declared ``src -> dst`` edge. ``get`` reads the current status from a state;
    ``with_status`` returns a new state with the status set to ``dst`` (states are immutable).

    ``effect(state, src, dst)`` runs AFTER the status change and returns the state with any side effects on
    OTHER fields applied (moving a balance, stamping a timestamp) — so a transition is not limited to
    swapping the status field. ``also(state)`` is an extra guard ANDed with "currently in ``src``", for a
    cross-cutting precondition the table itself does not encode (e.g. only post while the period is open)."""
    actions: list[Action[S]] = []
    for src, dsts in table.items():
        for dst in dsts:
            # default-arg capture pins src/dst per loop iteration (avoid late-binding); get/with_status/
            # effect/also are loop-invariant.
            def _apply(s: S, src: str = src, dst: str = dst) -> S:
                moved = with_status(s, dst)
                return effect(moved, src, dst) if effect is not None else moved

            def _enabled(s: S, src: str = src) -> bool:
                return get(s) == src and (also is None or also(s))

            actions.append(Action(name=name(src, dst), enabled=_enabled, apply=_apply))
    return actions


def replicated_transition_actions[S: Hashable](
    table: Table,
    instances: int | Iterable[Hashable],
    *,
    get: Callable[[S, Hashable], str],
    set_status: Callable[[S, Hashable, str], S],
    effect: Callable[[S, Hashable, str, str], S] | None = None,
    also: Callable[[S, Hashable], bool] | None = None,
    name: Callable[[Hashable, str, str], str] = lambda key, src, dst: f"{key}:{src}->{dst}",
) -> list[Action[S]]:
    """``N`` copies of ONE transition ``table`` — one state machine per instance — over a FLAT state, for a
    system of interchangeable entities (entries, replicas, jobs) that all obey the same lifecycle.

    ``instances`` is either an ``int`` ``N`` (keys ``0..N-1``) or an explicit iterable of keys. Unlike
    ``compose`` (which forces a ``Composite`` tuple state), the state stays a flat dataclass, so cross-
    instance invariants (``a + b == 0``, "at most one entry posting") remain expressible. The projections are
    per-instance: ``get(state, key)`` reads instance ``key``'s status; ``set_status(state, key, dst)`` sets
    it. ``effect(state, key, src, dst)`` applies per-instance side effects after the status change, and
    ``also(state, key)`` is a per-instance extra guard — exactly as in ``transition_actions`` but indexed by
    the instance."""
    keys = list(range(instances)) if isinstance(instances, int) else list(instances)
    actions: list[Action[S]] = []
    for key in keys:
        for src, dsts in table.items():
            for dst in dsts:

                def _apply(s: S, key: Hashable = key, src: str = src, dst: str = dst) -> S:
                    moved = set_status(s, key, dst)
                    return effect(moved, key, src, dst) if effect is not None else moved

                def _enabled(s: S, key: Hashable = key, src: str = src) -> bool:
                    return get(s, key) == src and (also is None or also(s, key))

                actions.append(Action(name=name(key, src, dst), enabled=_enabled, apply=_apply))
    return actions


def status_field_actions(table: Table, *, field: str = "status") -> list[Action[Any]]:
    """Convenience for the common case: states are frozen dataclasses whose status lives in a single
    field (default ``status``). Builds actions that read/replace that field via dataclasses.replace."""
    return transition_actions(
        table,
        get=lambda s: getattr(s, field),
        with_status=lambda s, dst: replace(s, **{field: dst}),
    )


def multi_status_field_actions(tables: Mapping[str, Table]) -> list[Action[Any]]:
    """For a dataclass with SEVERAL status fields, each driven by its own table (e.g. a control-plane
    ``World`` whose ``node``/``service``/``cert`` fields each follow a different ``ALLOWED[...]`` map):
    build every field's edge-actions at once. ``tables`` maps a field name to its table; action names
    are namespaced ``"<field>:<src>-><dst>"`` so they stay distinct across fields. musil fires every
    enabled action from every state, so the interleaved product of the per-field machines — every way
    the resources can advance concurrently — is explored for free."""
    actions: list[Action[Any]] = []
    for field, table in tables.items():
        actions.extend(
            transition_actions(
                table,
                get=lambda s, f=field: getattr(s, f),
                with_status=lambda s, dst, f=field: replace(s, **{f: dst}),
                name=lambda src, dst, f=field: f"{f}:{src}->{dst}",
            )
        )
    return actions


# A protocol table: state -> operation -> where that operation leaves you, or None for "legal
# here and does not move". This is the shape a published calling sequence actually has (FMI's
# `fmi3*`-per-mode tables, a TLS handshake, an HTTP upgrade dance): the edges are *labelled by
# the call*, and most calls are legal without changing the state. `Table` cannot express that —
# it only says which states follow which — so the two live side by side.
type Protocol[T] = Mapping[T, Mapping[str, T | None]]


def protocol_actions[S: Hashable, T](
    table: Protocol[T],
    *,
    get: Callable[[S], T],
    with_state: Callable[[S, T], S],
    name: Callable[[T, str], str] = lambda state, operation: f"{operation} in {state}",
) -> list[Action[S]]:
    """One Action per ``(state, operation)`` that moves, from a table of legal operations.

    The zero-drift argument, one level up from :func:`transition_actions`: a protocol table is
    what a *guard* needs anyway — "is this call legal where I am, and where does it leave me" —
    so pointing the checker at the same table means the sequence being verified is the sequence
    being enforced, not a second description of it.

    Operations mapped to ``None`` produce no action. They are legal and they stay put, so they
    add nothing to the reachable state space; a guard still has to know about them, which is why
    they belong in the table rather than being left out of it.

    ``get`` reads the protocol state out of your state; ``with_state`` returns a new one with it
    replaced. For a model whose state *is* the protocol state, those are ``lambda s: s`` and
    ``lambda _s, t: t``.
    """
    actions: list[Action[S]] = []
    for state, operations in table.items():
        for operation, target in operations.items():
            if target is None or target == state:
                continue
            actions.append(
                Action(
                    # default-arg capture pins state/target per loop iteration (late-binding).
                    name=name(state, operation),
                    enabled=lambda s, _f=state: get(s) == _f,
                    apply=lambda s, _t=target: with_state(s, _t),
                )
            )
    return actions


def protocol_operations[T](table: Protocol[T], state: T) -> frozenset[str]:
    """Every operation legal in ``state``, moving or not — what a guard checks against."""
    return frozenset(table.get(state, {}))


def declared_states(table: Table) -> set[str]:
    """Every state named in the table — sources (keys) plus every target."""
    return set(table) | {dst for dsts in table.values() for dst in dsts}


def terminal_states(table: Table) -> set[str]:
    """States with no outgoing transitions — absorbing sinks (a key mapped to an empty set, or a
    target that's never a source). Use to build a model's ``terminal`` predicate so a legitimate
    resting/sink state isn't reported as a deadlock."""
    return {s for s in declared_states(table) if not table.get(s)}


def assert_covers_table[S: Hashable](
    model: Model[S],
    table: Table,
    *,
    get: Callable[[S], str],
    max_states: int = 1_000_000,
    message: str | None = None,
) -> None:
    """Assert the model CONFORMS to the transition ``table`` — the zero-drift claim checked by musil instead
    of a hand-rolled action-name test.

    Over the whole reachable space, every step that CHANGES the status (read by ``get``) must go from ``src``
    to some ``dst`` in ``table[src]``: the model never makes a transition the table forbids. Actions built by
    ``transition_actions`` / ``replicated_transition_actions`` cannot drift ABOVE the table by construction,
    so this catches hand-written actions, a stale table, or an ``effect`` that produces an undeclared status
    change. Raises ``AssertionError`` listing every undeclared ``(src -> dst)`` status transition found.

    This checks CONFORMANCE (no forbidden transition), not completeness — a declared edge may be legitimately
    unreachable or held off by an extra guard, so "every table edge is exercised" is left to the caller (who
    knows which edges must be reachable); ``declared_states`` / ``terminal_states`` help build that check.
    ``get`` is the same status projection you pass to ``transition_actions``."""
    __tracebackhide__ = True
    graph = explore(model, max_states=max_states)
    undeclared: set[tuple[str, str]] = set()
    for s in graph.states:
        src = get(s)
        for _name, nxt in graph.edges.get(s, ()):
            dst = get(nxt)
            if src != dst and dst not in table.get(src, frozenset()):
                undeclared.add((src, dst))
    if undeclared:
        listing = ", ".join(f"{a} -> {b}" for a, b in sorted(undeclared))
        head = f"model makes status transitions not declared in the table: {listing}"
        raise AssertionError(f"{message}\n{head}" if message else head)
