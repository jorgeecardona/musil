"""The explicit-state core: a model is (initial states, guarded actions, invariants), and `check`
does a breadth-first sweep of every reachable state, reporting the first invariant violation or
deadlock with the shortest trace that reaches it.

States are plain immutable, hashable Python values — a frozen dataclass is the idiomatic choice.
Actions are pure: ``enabled(state)`` decides whether the action can fire, ``apply(state)`` returns
the resulting NEW state. Because the sweep fires *every* enabled action from *every* state,
modelling several concurrent actors is just handing it all their actions — the interleaving is
explored for free. That's the whole point: the bugs that matter are races, and BFS over
interleavings finds them.

This module is dependency-free and knows nothing about any particular domain."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, field

# A predicate that must hold in EVERY reachable state. Returns True when satisfied.
type Invariant[S] = Callable[[S], bool]


def _never(_state: object) -> bool:
    """Default ``terminal``: nothing is a sink, so every dead end counts as a deadlock."""
    return False


@dataclass(frozen=True, slots=True)
class Action[S: Hashable]:
    """A guarded, atomic transition. ``enabled`` decides if it can fire in a state; ``apply`` returns
    the resulting new state (states are immutable, so it never mutates). Keep both pure — the checker
    calls them many times and assumes no side effects."""

    name: str
    enabled: Callable[[S], bool]
    apply: Callable[[S], S]


@dataclass(frozen=True, slots=True)
class Step[S: Hashable]:
    """One link in a counterexample: the action that fired and the state it produced."""

    action: str
    state: S


@dataclass(slots=True)
class Model[S: Hashable]:
    """What to check: where to start, what can happen, and what must always hold.

    ``init`` is one state or several. ``actions`` are the (possibly multi-actor) transitions.
    ``invariants`` map a name → predicate that must hold in every reachable state. ``terminal``
    marks states allowed to have no enabled action (an absorbing sink like ``deleted``); any other
    dead end is reported as a deadlock."""

    init: S | Iterable[S]
    actions: Iterable[Action[S]]
    invariants: Mapping[str, Invariant[S]] = field(default_factory=dict)
    terminal: Callable[[S], bool] = _never

    def initial_states(self) -> tuple[S, ...]:
        init = self.init
        if _is_state_collection(init):
            return tuple(init)  # type: ignore[arg-type]
        return (init,)  # type: ignore[return-value]


def _is_state_collection(init: object) -> bool:
    """A list/tuple/set/generator of states means 'several initial states'. A frozen dataclass (the
    usual single state) is not treated as a collection even though some are technically iterable."""
    return isinstance(init, (list, tuple, set, frozenset)) or (
        hasattr(init, "__iter__") and not hasattr(init, "__dataclass_fields__")
    )


@dataclass(frozen=True, slots=True)
class Result[S: Hashable]:
    """The outcome. ``ok`` is True when the whole reachable space satisfied every invariant with no
    deadlock. Otherwise ``kind`` is ``"invariant"`` or ``"deadlock"``, ``invariant`` names the broken
    one, and ``trace`` is the shortest path from an initial state to the offending state."""

    ok: bool
    states_explored: int
    kind: str | None = None
    invariant: str | None = None
    trace: tuple[Step[S], ...] = ()
    truncated: bool = False  # True if the max_states cap was hit before the space was exhausted

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            cap = " (TRUNCATED at cap)" if self.truncated else ""
            return f"OK — {self.states_explored} states, no violations{cap}"
        head = (
            f"INVARIANT VIOLATED: {self.invariant}"
            if self.kind == "invariant"
            else "DEADLOCK (a non-terminal state with no enabled action)"
        )
        return f"{head}\n{format_trace(self.trace)}\n({self.states_explored} states explored)"


def format_trace[S: Hashable](trace: Iterable[Step[S]]) -> str:
    """Render a counterexample as ``Init: <state>`` then ``→ <action>  <state>`` per step."""
    lines: list[str] = []
    for i, step in enumerate(trace):
        if i == 0:
            lines.append(f"  Init: {step.state}")
        else:
            lines.append(f"  → {step.action}: {step.state}")
    return "\n".join(lines)


def check[S: Hashable](model: Model[S], *, max_states: int = 1_000_000) -> Result[S]:
    """Breadth-first sweep of every reachable state. Returns the first invariant violation or
    deadlock found (shortest trace, because BFS visits by increasing depth), else OK once the whole
    reachable space is exhausted. ``max_states`` is a runaway guard for unbounded models."""
    starts = model.initial_states()
    actions = tuple(model.actions)

    # parent[state] = (previous_state, action_name) — for reconstructing the shortest trace.
    parent: dict[S, tuple[S, str] | None] = {}
    seen: set[S] = set()
    frontier: list[S] = []
    for s in starts:
        if s not in seen:
            seen.add(s)
            parent[s] = None
            frontier.append(s)

    head = 0  # index into frontier instead of pop(0), so it behaves as a real FIFO queue
    while head < len(frontier):
        state = frontier[head]
        head += 1

        for name, inv in model.invariants.items():
            if not inv(state):
                return Result(
                    ok=False,
                    states_explored=len(seen),
                    kind="invariant",
                    invariant=name,
                    trace=_trace_to(parent, state),
                )

        fired = False
        for action in actions:
            if not action.enabled(state):
                continue
            fired = True
            nxt = action.apply(state)
            if nxt not in seen:
                seen.add(nxt)
                parent[nxt] = (state, action.name)
                frontier.append(nxt)
                if len(seen) >= max_states:
                    return Result(ok=True, states_explored=len(seen), truncated=True)

        if not fired and not model.terminal(state):
            return Result(
                ok=False,
                states_explored=len(seen),
                kind="deadlock",
                trace=_trace_to(parent, state),
            )

    return Result(ok=True, states_explored=len(seen))


def _trace_to[S: Hashable](
    parent: Mapping[S, tuple[S, str] | None], state: S
) -> tuple[Step[S], ...]:
    """Walk the parent chain back to an initial state, then return it forward as Steps."""
    chain: list[Step[S]] = []
    cur: S | None = state
    while cur is not None:
        entry = parent.get(cur)
        if entry is None:
            chain.append(Step(action="<init>", state=cur))
            break
        prev, action = entry
        chain.append(Step(action=action, state=cur))
        cur = prev
    chain.reverse()
    return tuple(chain)


@dataclass(frozen=True, slots=True)
class Graph[S: Hashable]:
    """The full reachable state graph: initial states, every reachable state, and the labelled
    transitions (``edges[s]`` = the ``(action_name, next_state)`` pairs out of ``s``). Built by
    ``explore`` and consumed by liveness checking and graph export. ``truncated`` flags hitting the
    ``max_states`` cap."""

    initial: tuple[S, ...]
    states: tuple[S, ...]
    edges: Mapping[S, tuple[tuple[str, S], ...]]
    truncated: bool = False


def explore[S: Hashable](model: Model[S], *, max_states: int = 1_000_000) -> Graph[S]:
    """Build the whole reachable state graph (no invariant checks). The shared exploration primitive
    behind liveness and graph export; ``check`` stays separate so it can early-exit with the shortest
    counterexample."""
    starts = model.initial_states()
    actions = tuple(model.actions)
    seen: dict[S, list[tuple[str, S]]] = {}
    frontier: list[S] = []
    for s in starts:
        if s not in seen:
            seen[s] = []
            frontier.append(s)

    head = 0
    truncated = False
    while head < len(frontier):
        state = frontier[head]
        head += 1
        out: list[tuple[str, S]] = []
        for action in actions:
            if not action.enabled(state):
                continue
            nxt = action.apply(state)
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
        initial=tuple(starts),
        states=tuple(seen),
        edges={s: tuple(out) for s, out in seen.items()},
        truncated=truncated,
    )
