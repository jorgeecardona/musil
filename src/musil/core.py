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

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

# A predicate that must hold in EVERY reachable state. Returns True when satisfied; False/None when
# violated. May instead return a string, which signals a violation AND carries a human-readable
# reason surfaced in the Result (e.g. when wrapping a richer checker that reports which sub-rule and
# entity broke). An empty string is a violation with no reason.
#
# CAUTION: a non-empty reason string is *truthy*, so do NOT evaluate an invariant with
# ``if not inv(state)`` — a returned reason would wrongly read as "holds". Let ``check`` /
# ``reachable_violations`` evaluate it, or build one with ``invariant_from_violations``.
type Invariant[S] = Callable[[S], bool | str | None]


def invariant_from_violations[S: Hashable](
    checker: Callable[[S], Sequence[object]],
    *,
    describe: Callable[[object], str] = str,
) -> Invariant[S]:
    """Adapt an external checker into a musil invariant. ``checker(state)`` returns a sequence of
    violation objects — empty means the state is fine. The resulting invariant returns ``True`` when
    that sequence is empty, else the first violation's ``describe(...)`` string (a reason surfaced in
    the counterexample). Use this to drive a real ``world -> [Violation]`` checker as an invariant
    without the ``not checker(s)`` footgun (a truthy reason string would otherwise read as 'holds')."""

    def inv(state: S) -> bool | str:
        result = checker(state)
        return True if not result else describe(result[0])

    return inv


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
    invariants: Mapping[str, Invariant[S]] = field(default_factory=dict[str, Invariant[S]])
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
    reason: str | None = None  # detail from a string-returning invariant (which sub-rule/entity)
    trace: tuple[Step[S], ...] = ()
    truncated: bool = False  # True if the max_states cap was hit before the space was exhausted

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            cap = " (TRUNCATED at cap)" if self.truncated else ""
            return f"OK — {self.states_explored} states, no violations{cap}"
        if self.kind == "invariant":
            head = f"INVARIANT VIOLATED: {self.invariant}"
            if self.reason:
                head += f" — {self.reason}"
        else:
            head = "DEADLOCK (a non-terminal state with no enabled action)"
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


def check[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
) -> Result[S]:
    """Breadth-first sweep of every reachable state. Returns the first invariant violation or
    deadlock found (shortest trace, because BFS visits by increasing depth), else OK once the whole
    reachable space is exhausted. ``max_states`` is a runaway guard for unbounded models.

    ``canonicalize`` enables **symmetry reduction** (OPT-IN, soundness is the caller's obligation):
    map each state to a canonical representative of its symmetry-equivalence class and only that
    representative is explored — collapsing interchangeable components (e.g. sort the per-worker
    slices) so the space stops blowing up combinatorially. SOUND only if it is a genuine symmetry of
    the model: every action commutes with it and every invariant is constant across each class.
    Getting that wrong silently drops reachable states (misses bugs), so VALIDATE it on small
    instances with ``symmetry_reduction_sound`` before trusting it on large ones. Counterexample
    traces are then witnesses *up to symmetry* (each step a real action followed by a renaming)."""
    starts = model.initial_states()
    actions = tuple(model.actions)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)

    # parent[state] = (previous_state, action_name) — for reconstructing the shortest trace.
    parent: dict[S, tuple[S, str] | None] = {}
    seen: set[S] = set()
    frontier: list[S] = []
    for s0 in starts:
        s = canon(s0)
        if s not in seen:
            seen.add(s)
            parent[s] = None
            frontier.append(s)

    head = 0  # index into frontier instead of pop(0), so it behaves as a real FIFO queue
    while head < len(frontier):
        state = frontier[head]
        head += 1

        for name, inv in model.invariants.items():
            verdict = inv(state)
            # A string return is a violation carrying a reason; otherwise legacy truthiness:
            # falsy (False/None/"") is a violation, truthy holds.
            if isinstance(verdict, str):
                return Result(
                    ok=False, states_explored=len(seen), kind="invariant", invariant=name,
                    reason=verdict or None, trace=_trace_to(parent, state),
                )
            if not verdict:
                return Result(
                    ok=False, states_explored=len(seen), kind="invariant", invariant=name,
                    trace=_trace_to(parent, state),
                )

        fired = False
        for action in actions:
            if not action.enabled(state):
                continue
            fired = True
            nxt = canon(action.apply(state))
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


def explore[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
) -> Graph[S]:
    """Build the whole reachable state graph (no invariant checks). The shared exploration primitive
    behind liveness and graph export; ``check`` stays separate so it can early-exit with the shortest
    counterexample. ``canonicalize`` enables symmetry reduction (see ``check``); validate it with
    ``symmetry_reduction_sound`` before trusting it."""
    starts = model.initial_states()
    actions = tuple(model.actions)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    seen: dict[S, list[tuple[str, S]]] = {}
    frontier: list[S] = []
    for s0 in starts:
        s = canon(s0)
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
        initial=tuple(canon(s) for s in starts),
        states=tuple(seen),
        edges={s: tuple(out) for s, out in seen.items()},
        truncated=truncated,
    )


def symmetry_reduction_sound[S: Hashable](
    model: Model[S],
    canonicalize: Callable[[S], S],
    *,
    max_states: int = 1_000_000,
) -> bool:
    """Validate a symmetry-reduction ``canonicalize`` for ``model`` on a (bounded) instance — the
    soundness gate that should pass before ``check(..., canonicalize=...)`` is trusted on larger
    instances.

    It explores the model fully and reduced and confirms two things agree:
    (1) the reduced run visited exactly the canonical quotient of the full reachable set
        (``{canonicalize(s) for s in full} == set(reduced)``) — reachability coverage; and
    (2) the SAME set of invariants is violable in both runs — which additionally certifies that every
        invariant is constant across each symmetry class (a state and its representative agree).

    Both matter: (1) alone passes for a lossy projection that merges non-equivalent states, but (2)
    then catches it because an invariant violated on a dropped state is no longer violated on its
    (information-losing) representative. Because the full run is the trusted reference, any unsound
    ``canonicalize`` — not a real symmetry, or a real symmetry against a non-class-constant invariant —
    makes one of these disagree and returns False. (Deadlock-freedom under reduction is NOT covered;
    validate that separately.) Returns False if either run truncated at ``max_states`` (inconclusive)."""
    full = explore(model, max_states=max_states)
    reduced = explore(model, max_states=max_states, canonicalize=canonicalize)
    if full.truncated or reduced.truncated:
        return False
    coverage = {canonicalize(s) for s in full.states} == set(reduced.states)
    full_violated = {v.invariant for v in reachable_violations(model, max_states=max_states)}
    reduced_violated = {
        v.invariant
        for v in reachable_violations(model, max_states=max_states, canonicalize=canonicalize)
    }
    return coverage and full_violated == reduced_violated


@dataclass(frozen=True, slots=True)
class StateViolation[S: Hashable]:
    """One reachable state that breaks one invariant. ``reason`` carries the detail from a
    string-returning invariant, if any."""

    state: S
    invariant: str
    reason: str | None = None


def reachable_violations[S: Hashable](
    model: Model[S], *, max_states: int = 1_000_000, canonicalize: Callable[[S], S] | None = None
) -> list[StateViolation[S]]:
    """Every ``(reachable state, broken invariant)`` pair — an exhaustive audit, where ``check`` stops
    at the first. Use it to enumerate *all* the invalid states a model can reach — e.g. to derive the
    exact set of cross-resource combinations that guards must exclude — instead of one shortest
    counterexample. Deadlock is not considered (use ``check`` for that). Each invariant is evaluated
    with the same semantics as ``check``: a string return is a violation carrying that reason.
    ``canonicalize`` applies symmetry reduction (see ``check``)."""
    g = explore(model, max_states=max_states, canonicalize=canonicalize)
    out: list[StateViolation[S]] = []
    for s in g.states:
        for name, inv in model.invariants.items():
            verdict = inv(s)
            if isinstance(verdict, str):
                out.append(StateViolation(state=s, invariant=name, reason=verdict or None))
            elif not verdict:
                out.append(StateViolation(state=s, invariant=name))
    return out
