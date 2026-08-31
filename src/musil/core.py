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

import itertools
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, is_dataclass, replace
from dataclasses import fields as _dc_fields
from typing import Any, Literal, NoReturn, Protocol, cast

# A predicate that must hold in EVERY reachable state. Returns True when satisfied; False/None when
# violated. May instead return a string, which signals a violation AND carries a human-readable
# reason surfaced in the Result (e.g. when wrapping a richer checker that reports which sub-rule and
# entity broke). An empty string is a violation with no reason.
#
# CAUTION: a non-empty reason string is *truthy*, so do NOT evaluate an invariant with
# ``if not inv(state)`` — a returned reason would wrongly read as "holds". Let ``check`` /
# ``reachable_violations`` evaluate it, or build one with ``invariant_from_violations``.
type Invariant[S] = Callable[[S], bool | str | None]
# An EDGE (transition) invariant: (before, action_name, after) -> holds? A str is a violation carrying a
# reason (as for state invariants); otherwise falsy is a violation. Checked on every explored edge.
type EdgeInvariant[S] = Callable[[S, str, S], bool | str | None]


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
    calls them many times and assumes no side effects.

    ``fair`` tags this action's fairness for ``check_liveness``: ``"weak"`` (weakly fair), ``"strong"``
    (strongly fair), or ``None`` (unfair — a fault). With no explicit ``fair=`` / ``fair_strong=`` tuple,
    ``check_liveness`` derives its fairness sets from these tags, so the fair-ours / unfair-faults
    distinction lives on the action that knows what it is, not in a parallel name list kept in sync by hand."""

    name: str
    enabled: Callable[[S], bool]
    apply: Callable[[S], S]
    fair: Literal["weak", "strong"] | None = None


@dataclass(frozen=True, slots=True)
class Step[S: Hashable]:
    """One link in a counterexample: the action that fired and the state it produced."""

    action: str
    state: S


@dataclass(slots=True)
class Model[S: Hashable]:
    """What to check: where to start, what can happen, and what must always hold.

    ``init`` is one state or several. ``actions`` are the (possibly multi-actor) transitions — a STATIC
    list. ``invariants`` map a name → predicate that must hold in every reachable state. ``terminal``
    marks states allowed to have no enabled action (an absorbing sink like ``deleted``); any other
    dead end is reported as a deadlock.

    ``actions_fn``, if given, supplies the actions available IN A GIVEN STATE (``actions_fn(state) ->
    Iterable[Action]``) and takes precedence over the static ``actions``. Use it for a STATE-DEPENDENT
    action space — e.g. a ``possibleActions(state)`` / offered-menu enumerator, or a parameterized
    bounded-action algebra whose enabled bindings depend on the state — instead of hand-guarding a large
    static product. Each returned Action's own ``enabled`` still applies (return already-enabled actions,
    or let their guards filter).

    ``footprint``, if given, is a ``state -> hashable`` PROJECTION of the sub-state that ``actions_fn``
    reads, and turns on MEMOIZATION: the enumerated action list is cached on ``footprint(state)`` and
    reused across every state that shares a footprint. Use it when ``actions_fn`` is expensive (a menu
    builder that constructs objects per call) but depends on only part of the state — the framework-level
    version of the ``lru_cache`` such callers hand-write. It has effect only with ``actions_fn`` (there is
    nothing to recompute for the static ``actions``). Unlike ``canonicalize`` it does NOT quotient the
    space, so an unsound footprint does not shrink the sweep — it feeds a state the WRONG memoized menu, so
    successors go wrong and reachable states (and the violations only they reach) can be missed. The
    obligation is that ``actions_fn`` yields the SAME menu for any two states with equal footprint; gate it
    with ``footprint_sound`` before trusting it."""

    init: S | Iterable[S]
    actions: Iterable[Action[S]] = ()
    invariants: Mapping[str, Invariant[S]] = field(default_factory=dict[str, Invariant[S]])
    terminal: Callable[[S], bool] = _never
    actions_fn: Callable[[S], Iterable[Action[S]]] | None = None
    footprint: Callable[[S], Hashable] | None = None
    # EDGE (transition) invariants: name -> predicate over (before, action_name, after). Checked on every
    # explored edge by ``check`` / ``check_all`` / ``check_of`` — for properties about the STEP, not the state
    # (a state that is legitimately reachable, but reached by an illegal edge). See ``never`` for the common
    # "forbid this transition" case.
    edge_invariants: Mapping[str, EdgeInvariant[S]] = field(default_factory=dict[str, "EdgeInvariant[S]"])

    def initial_states(self) -> tuple[S, ...]:
        init = self.init
        if _is_state_collection(init):
            return tuple(init)  # type: ignore[arg-type]
        return (init,)  # type: ignore[return-value]


def _is_state_collection(init: object) -> bool:
    """A list/tuple/set/generator of states means 'several initial states'. A single RICH state is never a
    collection even when it is technically iterable — this covers a frozen dataclass AND a pydantic model
    (pydantic v2 BaseModel is iterable, yielding (field, value) pairs; without this guard a single pydantic
    state would be shredded into field tuples by ``initial_states``).

    A ``str`` (so also a ``StrEnum`` member, and ``bytes``) is one state and never a collection of
    them, even though iterating it succeeds. Without this the check runs happily on a model whose
    states are the *characters* of the intended one and reports nothing wrong, which is the worst
    kind of wrong -- a green result for a question nobody asked."""
    if isinstance(init, (str, bytes)):
        return False
    if isinstance(init, (list, tuple, set, frozenset)):
        return True
    if hasattr(init, "__dataclass_fields__") or hasattr(init, "model_fields"):
        return False  # a dataclass instance or a pydantic model = ONE state
    return hasattr(init, "__iter__")


def _schema_always_enabled(_state: object, **_kw: object) -> bool:
    """Default ``ActionSchema.enabled``: the schema's actions are always firable (guards, if any, live
    in the concrete ``Action`` or the ``actions_fn`` that bounds the domains)."""
    return True


@dataclass(frozen=True, slots=True)
class ActionSchema[S: Hashable]:
    """A PARAMETERIZED action: a ``name``, typed parameter slots each with a BOUNDED domain, and pure
    ``apply``/``enabled`` that take those parameters as keyword arguments. ``enumerate_actions`` expands it
    into one concrete ``Action`` per binding in the cartesian product of the domains.

    This makes the bounded-action-algebra pattern first-class: a closed union whose members declare typed
    parameter slots with bounded domains, from which consumers construct concrete actions (the shape THE
    ACTION LAW describes). ``params`` maps slot name → its finite domain; ``apply(state, **params) -> state``
    and ``enabled(state, **params) -> bool`` receive the bound arguments. A schema with no params yields a
    single concrete action."""

    name: str
    apply: Callable[..., S]
    params: Mapping[str, Iterable[object]] = field(default_factory=dict[str, Iterable[object]])
    enabled: Callable[..., bool] = _schema_always_enabled


def enumerate_actions[S: Hashable](schemas: Iterable[ActionSchema[S]]) -> list[Action[S]]:
    """Expand parameterized ``ActionSchema``s into concrete musil ``Action``s — the cartesian product over
    each schema's bounded parameter domains, one Action per binding (a zero-param schema → one Action). Each
    argument tuple is bound BY VALUE so the generated closures don't capture the loop variable. The concrete
    action's name encodes its binding (e.g. ``add_filter{field='status', value='active'}``) so counterexample
    traces read as filled actions. Pair with a static ``Model(actions=enumerate_actions(...))`` for a bounded
    parameterized algebra, or call it inside ``actions_fn`` to bound the domains per state."""
    out: list[Action[S]] = []
    for sch in schemas:
        names = list(sch.params.keys())
        domains = [list(sch.params[n]) for n in names]
        for combo in (itertools.product(*domains) if names else [()]):
            binding = dict(zip(names, combo, strict=True))
            label = sch.name if not binding else sch.name + "{" + ", ".join(f"{k}={v!r}" for k, v in binding.items()) + "}"
            out.append(
                Action(
                    name=label,
                    enabled=(lambda state, _s=sch, _b=binding: _s.enabled(state, **_b)),
                    apply=(lambda state, _s=sch, _b=binding: _s.apply(state, **_b)),
                )
            )
    return out


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
    # For an infinite-run (LTL lasso) counterexample: the index in ``trace`` where the cycle begins — the
    # state reached, then repeated forever. None for a finite counterexample (invariant/deadlock) or ok.
    loop: int | None = None

    @property
    def action_names(self) -> tuple[str, ...]:
        """The action names along the counterexample ``trace``, excluding the synthetic ``<init>`` step —
        the sequence of steps that reproduces the violation (empty on success)."""
        return tuple(step.action for step in self.trace if step.action != "<init>")

    @property
    def witness(self) -> S | None:
        """The offending state — the last state of the counterexample ``trace`` (the one that breaks the
        invariant or deadlocks) — or None on success / an empty trace."""
        return self.trace[-1].state if self.trace else None

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
        elif self.kind == "edge-invariant":
            head = f"EDGE INVARIANT VIOLATED: {self.invariant} (on the last transition)"
            if self.reason:
                head += f" — {self.reason}"
        elif self.kind == "ltl":
            head = f"LTL VIOLATED: {self.reason}" if self.reason else "LTL VIOLATED"
        else:
            head = "DEADLOCK (a non-terminal state with no enabled action)"
        return f"{head}\n{format_trace(self.trace, loop=self.loop)}\n({self.states_explored} states explored)"


def format_trace[S: Hashable](
    trace: Iterable[Step[S]], *, render: Callable[[S], str] | None = None, loop: int | None = None
) -> str:
    """Render a counterexample as ``Init: <state>`` then ``→ <action>  <state>`` per step. ``render`` customises
    how each state is shown (default ``str``) — useful for rich states whose full repr is noisy. ``loop`` is
    the index of a lasso's cycle start: a ``--- loops forever ---`` marker is emitted after that state, so an
    infinite-run (LTL) counterexample shows where the repeating suffix begins."""
    show = render if render is not None else str
    lines: list[str] = []
    for i, step in enumerate(trace):
        lines.append(f"  Init: {show(step.state)}" if i == 0 else f"  → {step.action}: {show(step.state)}")
        if loop is not None and i == loop:
            lines.append("  --- loops forever ---")
    return "\n".join(lines)


def _state_fields(state: object) -> dict[str, object] | None:
    """The named fields of a state as a dict, for diffing — pydantic (``model_dump``), dataclass, or Mapping.
    Returns None for states that can't be introspected (the diff renderer then falls back to the full repr)."""
    dump = getattr(state, "model_dump", None)
    if callable(dump):
        try:
            return dict(cast("Mapping[str, object]", dump()))
        except Exception:  # a state that won't dump just isn't diffable
            return None
    if is_dataclass(state) and not isinstance(state, type):
        return {f.name: getattr(state, f.name) for f in _dc_fields(state)}
    if isinstance(state, Mapping):
        return dict(cast("Mapping[str, object]", state))
    return None


def format_trace_diff[S: Hashable](trace: Iterable[Step[S]], *, render: Callable[[object], str] = repr) -> str:
    """Like ``format_trace`` but shows only the FIELDS THAT CHANGED between consecutive states — the init in
    full, then per step the ``field=new`` deltas. Far more readable for rich states (dataclass / pydantic /
    Mapping) where a full dump per step drowns the one thing the action changed. Falls back to the full state
    repr for any state whose fields can't be introspected."""
    lines: list[str] = []
    prev: dict[str, object] | None = None
    for i, step in enumerate(trace):
        cur = _state_fields(step.state)
        if i == 0:
            body = render(step.state) if cur is None else ", ".join(f"{k}={render(v)}" for k, v in cur.items())
            lines.append(f"  Init: {body}")
        elif cur is None or prev is None:
            lines.append(f"  → {step.action}: {render(step.state)}")
        else:
            delta = {k: v for k, v in cur.items() if prev.get(k) != v}
            body = ", ".join(f"{k}={render(v)}" for k, v in delta.items()) or "(no field change)"
            lines.append(f"  → {step.action}: {body}")
        if cur is not None:
            prev = cur
    return "\n".join(lines)


class Verdict(Protocol):
    """What ``assert_ok`` needs from a result: a boolean verdict and a renderer. Every musil result
    type satisfies it structurally -- ``Result``, ``LivenessResult``, ``ConformanceResult``,
    ``RefinementResult``, ``OpenResult``, ``SimReport``."""

    @property
    def ok(self) -> bool: ...

    def __str__(self) -> str: ...


def assert_ok(result: Verdict, message: str | None = None, *, truncated: Literal["fail", "ok"] = "fail") -> None:
    """Assert a result is OK, failing with its *rendered* form -- the counterexample, not the repr.

    ``assert check(model)`` inside a test runner reports the result's **repr**, and pytest shortens a
    long one by eliding its middle: the trace comes out as
    ``trace=(Step(action='<init>', s...Step(action='inc', state=S(n=3)))``, with the initial state
    cut, followed by the whole ``Model`` repr (lambda addresses included) as assertion context. The
    counterexample is not merely ugly there, it is incomplete. This raises ``AssertionError(str(result))``
    instead, so the failure message is the ``Init: ... -> action: ...`` rendering ``__str__`` already
    produces. ``message`` is prefixed when the same assertion runs over several models.

    ``truncated`` governs a passing-but-TRUNCATED result — the ``max_states`` cap stopped the sweep before
    the space was exhausted, so a green verdict proves nothing about the unexplored part. The default
    ``"fail"`` rejects it (raise ``max_states``, or pass ``truncated="ok"`` to accept an inconclusive pass);
    this closes the quiet hole of a truncated green being read as proof.

    Works on any musil result (they all carry ``ok`` and a meaningful ``__str__``), and needs no test
    framework -- it is a plain ``AssertionError``, so ``unittest`` and bare ``assert`` get it too."""
    # pytest hides a frame that sets this, which is the difference between a clean failure and one
    # that reprints the elided repr as the helper's arguments. It is an ordinary local otherwise, so
    # nothing here depends on pytest being installed.
    __tracebackhide__ = True
    if not result.ok:
        rendered = str(result)
        raise AssertionError(f"{message}\n{rendered}" if message else rendered)
    if truncated == "fail" and getattr(result, "truncated", False):
        head = "check passed but TRUNCATED at max_states -- a truncated green proves nothing; raise max_states or pass truncated='ok'"
        rendered = f"{head}\n{result}"
        raise AssertionError(f"{message}\n{rendered}" if message else rendered)


def assert_violates(
    result: Verdict,
    message: str | None = None,
    *,
    kind: str | None = None,
    invariant: str | None = None,
    via: Iterable[str] | None = None,
    where: Callable[[Any], bool] | None = None,
) -> None:
    """Assert a check FOUND a violation — the red-side counterpart to ``assert_ok`` — optionally pinning the
    details, rendering the full counterexample on any mismatch.

    Fails if ``result.ok`` (no violation was found). Then, for each given constraint: ``kind`` must equal the
    verdict kind (``"invariant"`` / ``"deadlock"`` / ``"p-unreachable"`` / ``"fair-cycle"`` / ``"ltl"``);
    ``invariant`` must equal the broken invariant name; every name in ``via`` must appear among the
    counterexample's ``action_names``; and ``where`` must hold on the ``witness`` (the offending state).
    Works on ``Result`` and ``LivenessResult`` alike (both expose ``kind`` / ``action_names`` / ``witness``);
    ``message`` is prefixed as in ``assert_ok``."""
    __tracebackhide__ = True

    def fail(reason: str) -> NoReturn:
        rendered = f"{reason}\n{result}"
        raise AssertionError(f"{message}\n{rendered}" if message else rendered)

    if result.ok:
        fail("expected a violation, but the check passed")
    got_kind = getattr(result, "kind", None)
    if kind is not None and got_kind != kind:
        fail(f"expected kind {kind!r}, got {got_kind!r}")
    got_inv = getattr(result, "invariant", None)
    if invariant is not None and got_inv != invariant:
        fail(f"expected broken invariant {invariant!r}, got {got_inv!r}")
    if via is not None:
        names: tuple[str, ...] = getattr(result, "action_names", ())
        missing = [a for a in via if a not in names]
        if missing:
            fail(f"expected actions {missing!r} in the counterexample, but its actions were {list(names)!r}")
    if where is not None:
        w = getattr(result, "witness", None)
        if w is None or not where(w):
            fail(f"the witness state {w!r} did not satisfy `where`")


def actions_source[S: Hashable](model: Model[S]) -> Callable[[S], Iterable[Action[S]]]:
    """The per-state action list the BFS loops iterate. With a ``Model.footprint`` and an ``actions_fn``
    the enumerated list is MEMOIZED on ``footprint(state)`` — states sharing a footprint reuse the tuple
    instead of re-running ``actions_fn`` — so an expensive enumerator runs once per footprint, not once
    per state (``footprint_sound`` is the obligation). Without a footprint it is ``actions_fn`` itself;
    with only static ``actions`` it is a constant. ``cache.get`` is disambiguated with ``is None`` so a
    genuinely empty menu (``()``) is a hit, not re-enumerated."""
    actions_fn = model.actions_fn
    if actions_fn is None:
        static_actions = tuple(model.actions)
        return lambda _state: static_actions
    footprint = model.footprint
    if footprint is None:
        return actions_fn
    cache: dict[Hashable, tuple[Action[S], ...]] = {}

    def source(state: S) -> Iterable[Action[S]]:
        fp = footprint(state)
        got = cache.get(fp)
        if got is None:
            got = tuple(actions_fn(state))
            cache[fp] = got
        return got

    return source


def _seed_frontier[S: Hashable](
    starts: tuple[S, ...], canon: Callable[[S], S], ident: Callable[[S], Hashable]
) -> tuple[set[Hashable], dict[Hashable, tuple[Hashable, str] | None], dict[Hashable, S], list[S]]:
    """Seed the BFS bookkeeping from the initial states — shared by ``check``/``check_all`` so the two
    cannot drift in how they start the sweep (canonicalize, identity dedup, ``parent=None`` roots)."""
    seen: set[Hashable] = set()
    parent: dict[Hashable, tuple[Hashable, str] | None] = {}
    states_by_id: dict[Hashable, S] = {}
    frontier: list[S] = []
    for s0 in starts:
        s = canon(s0)
        sid = ident(s)
        if sid not in seen:
            seen.add(sid)
            parent[sid] = None
            states_by_id[sid] = s
            frontier.append(s)
    return seen, parent, states_by_id, frontier


def _successors[S: Hashable](
    source: Callable[[S], Iterable[Action[S]]], canon: Callable[[S], S], state: S
) -> Iterator[tuple[str, S]]:
    """The canonical enabled ``(action_name, successor)`` pairs out of ``state``, lazily. This is the ONE
    place a successor is computed as ``canon(action.apply(state))`` — shared by ``_expand`` (check/check_all)
    and ``explore`` so the successor canonicalization (the 089aed0 bug: canonicalized in one path but not the
    other) cannot drift. Lazy, so a caller that stops early on ``max_states`` computes no further
    successors, matching the hand-written loops exactly."""
    for action in source(state):
        if action.enabled(state):
            yield action.name, canon(action.apply(state))


def _expand[S: Hashable](
    state: S,
    sid: Hashable,
    source: Callable[[S], Iterable[Action[S]]],
    canon: Callable[[S], S],
    ident: Callable[[S], Hashable],
    seen: set[Hashable],
    parent: dict[Hashable, tuple[Hashable, str] | None],
    states_by_id: dict[Hashable, S],
    frontier: list[S],
    max_states: int,
) -> tuple[bool, bool]:
    """Fire every enabled action from ``state`` (via ``_successors``), adding each new successor to the
    frontier and recording its parent edge. Returns ``(fired, truncated)``: ``fired`` whether any action
    was enabled (for deadlock detection), ``truncated`` whether the ``max_states`` cap was hit. The single
    successor-expansion shared by ``check``/``check_all``."""
    fired = False
    for name, nxt in _successors(source, canon, state):
        fired = True
        nid = ident(nxt)
        if nid not in seen:
            seen.add(nid)
            parent[nid] = (sid, name)
            states_by_id[nid] = nxt
            frontier.append(nxt)
            if len(seen) >= max_states:
                return fired, True
    return fired, False


def _extend_frontier[S: Hashable](
    successors: Iterable[tuple[str, S]],
    sid: Hashable,
    ident: Callable[[S], Hashable],
    seen: set[Hashable],
    parent: dict[Hashable, tuple[Hashable, str] | None],
    states_by_id: dict[Hashable, S],
    frontier: list[S],
    max_states: int,
) -> tuple[bool, bool]:
    """``_expand`` from ALREADY-COMPUTED successors: same frontier bookkeeping and ``(fired, truncated)``
    contract, but the caller has already materialized the ``(name, canon(next))`` pairs — so the ONE place
    check/check_all need the successors anyway (the edge-invariant scan) feeds the expansion instead of
    ``_successors`` running a second time. Truncation matches ``_expand`` exactly: the pairs are in the same
    order, deduped by identity, and the cap stops the walk at the same point."""
    fired = False
    for name, nxt in successors:
        fired = True
        nid = ident(nxt)
        if nid not in seen:
            seen.add(nid)
            parent[nid] = (sid, name)
            states_by_id[nid] = nxt
            frontier.append(nxt)
            if len(seen) >= max_states:
                return fired, True
    return fired, False


def check[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
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
    traces are then witnesses *up to symmetry* (each step a real action followed by a renaming).

    ``key`` maps a state to a HASHABLE identity used ONLY for the visited-set + trace bookkeeping. Supply
    it when the state itself is NOT hashable (e.g. a pydantic model or a dataclass with ``list`` fields) so
    it can be checked directly, with no wrapper type. Its result need not be a state — the rich states are
    kept for the trace. It carries no SYMMETRY obligation (it does not quotient the space), but it DOES carry
    an INJECTIVITY obligation: distinct reachable states (post-``canonicalize``) must map to distinct keys. A
    collision prunes the second state AND all its successors from the sweep — silently dropping reachable
    states and any violations only they reach, exactly the unsoundness ``canonicalize`` warns about, but with
    no validator. When unsure, make ``key`` a lossless encoding of the whole state (e.g. every field). Unlike
    ``canonicalize``, a NON-injective ``key`` is never sound. (``explore`` and the tools built on it still
    require hashable states.) The model's ``actions_fn`` (if set) supplies the per-state action list;
    otherwise the static ``actions`` are used."""
    source = actions_source(model)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    ident: Callable[[S], Hashable] = key if key is not None else (lambda s: s)

    # Keyed by state IDENTITY (``ident``): parent[id] = (prev_id, action); states_by_id keeps the rich state
    # for trace reconstruction. With no ``key`` the identity IS the state (today's behaviour).
    seen, parent, states_by_id, frontier = _seed_frontier(model.initial_states(), canon, ident)

    head = 0  # index into frontier instead of pop(0), so it behaves as a real FIFO queue
    while head < len(frontier):
        state = frontier[head]
        head += 1
        sid = ident(state)

        for name, inv in model.invariants.items():
            verdict = inv(state)
            # A string return is a violation carrying a reason; otherwise legacy truthiness:
            # falsy (False/None/"") is a violation, truthy holds.
            if isinstance(verdict, str):
                return Result(
                    ok=False, states_explored=len(seen), kind="invariant", invariant=name,
                    reason=verdict or None, trace=_trace_to(parent, states_by_id, sid),
                )
            if not verdict:
                return Result(
                    ok=False, states_explored=len(seen), kind="invariant", invariant=name,
                    trace=_trace_to(parent, states_by_id, sid),
                )

        if model.edge_invariants:  # off by default: compute successors ONCE here and reuse them to expand
            successors: list[tuple[str, S]] = []
            for name, nxt in _successors(source, canon, state):
                successors.append((name, nxt))
                for iname, einv in model.edge_invariants.items():
                    verdict = einv(state, name, nxt)
                    if isinstance(verdict, str) or not verdict:
                        return Result(
                            ok=False, states_explored=len(seen), kind="edge-invariant", invariant=iname,
                            reason=(verdict or None) if isinstance(verdict, str) else None,
                            trace=(*_trace_to(parent, states_by_id, sid), Step(action=name, state=nxt)),
                        )
            fired, truncated = _extend_frontier(
                successors, sid, ident, seen, parent, states_by_id, frontier, max_states
            )
        else:
            fired, truncated = _expand(
                state, sid, source, canon, ident, seen, parent, states_by_id, frontier, max_states
            )
        if truncated:
            return Result(ok=True, states_explored=len(seen), truncated=True)
        if not fired and not model.terminal(state):
            return Result(
                ok=False,
                states_explored=len(seen),
                kind="deadlock",
                trace=_trace_to(parent, states_by_id, sid),
            )

    return Result(ok=True, states_explored=len(seen))


_DEADLOCK = object()  # dedup sentinel for the (single) deadlock entry in check_all — never a violation key


def _bucketer(distinct_by: str | Callable[[str, str | None], Hashable]) -> Callable[[str, str | None], Hashable]:
    """Normalise ``check_all``'s ``distinct_by`` into a ``(invariant_name, reason) -> key`` function."""
    if callable(distinct_by):
        return distinct_by
    if distinct_by == "reason":
        return lambda name, reason: (name, reason)
    return lambda name, reason: name


def check_all[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
    distinct_by: str | Callable[[str, str | None], Hashable] = "invariant",
) -> list[Result[S]]:
    """Exhaustive ``check``: instead of stopping at the FIRST problem, sweep the WHOLE reachable space and
    return the SHORTEST witnessing trace for EACH DISTINCT violation (plus deadlock, once). For a review/audit
    pass where you want the full list of what is broken, not one counterexample at a time.

    ``distinct_by`` controls how violations are bucketed:
      - ``"invariant"`` (default) — one entry per broken invariant NAME;
      - ``"reason"`` — one entry per ``(invariant, reason)`` pair (finer);
      - a CALLABLE ``(invariant_name, reason) -> hashable`` — bucket by a caller-defined CLASS. Use this when
        the reason embeds variable detail (ids, counts) that would otherwise explode into many spurious
        "distinct" entries: return e.g. the failure category so all instances collapse to one witness.
    Results are ordered shortest-trace-first (BFS visits by increasing depth), so the most easily-triggered
    problems lead. An EMPTY list means the model is fully correct (the analog of ``check(...).ok`` being True).
    Unlike ``reachable_violations`` (one ``StateViolation`` per offending state, no path), each entry here is a
    full ``Result`` with a reproducible ``trace``. Shares ``check``'s invariant semantics, ``canonicalize``
    (symmetry reduction), ``key`` (hashable identity for non-hashable states — must be INJECTIVE over reachable
    states; see ``check`` for the full contract), and the model's ``actions_fn``."""
    source = actions_source(model)
    canon: Callable[[S], S] = canonicalize if canonicalize is not None else (lambda s: s)
    ident: Callable[[S], Hashable] = key if key is not None else (lambda s: s)
    bucket = _bucketer(distinct_by)

    seen, parent, states_by_id, frontier = _seed_frontier(model.initial_states(), canon, ident)

    found: dict[object, Result[S]] = {}  # bucket key → first (⇒ shortest, BFS) witnessing Result
    truncated = False
    head = 0
    while head < len(frontier):
        state = frontier[head]
        head += 1
        sid = ident(state)

        for name, inv in model.invariants.items():
            verdict = inv(state)
            reason = verdict if isinstance(verdict, str) else None
            if not (isinstance(verdict, str) or not verdict):
                continue  # holds
            bkey = bucket(name, reason)
            if bkey not in found:
                found[bkey] = Result(
                    ok=False, states_explored=len(seen), kind="invariant",
                    invariant=name, reason=reason or None, trace=_trace_to(parent, states_by_id, sid),
                )

        if model.edge_invariants:  # off by default: compute successors ONCE here and reuse them to expand
            edge_successors: list[tuple[str, S]] = []
            for aname, nxt in _successors(source, canon, state):
                edge_successors.append((aname, nxt))
                for iname, einv in model.edge_invariants.items():
                    everdict = einv(state, aname, nxt)
                    if not (isinstance(everdict, str) or not everdict):
                        continue  # holds
                    ereason = everdict if isinstance(everdict, str) else None
                    ekey = ("edge-invariant", bucket(iname, ereason))  # namespaced so it never collides
                    if ekey not in found:
                        found[ekey] = Result(
                            ok=False, states_explored=len(seen), kind="edge-invariant", invariant=iname,
                            reason=ereason or None,
                            trace=(*_trace_to(parent, states_by_id, sid), Step(action=aname, state=nxt)),
                        )
            fired, truncated = _extend_frontier(
                edge_successors, sid, ident, seen, parent, states_by_id, frontier, max_states
            )
        else:
            fired, truncated = _expand(
                state, sid, source, canon, ident, seen, parent, states_by_id, frontier, max_states
            )
        if not fired and not model.terminal(state) and _DEADLOCK not in found:
            found[_DEADLOCK] = Result(
                ok=False, states_explored=len(seen), kind="deadlock", trace=_trace_to(parent, states_by_id, sid),
            )
        if truncated:
            break

    results = sorted(found.values(), key=lambda r: len(r.trace))
    if truncated:
        results = [replace(r, truncated=True) for r in results]
    return results


def _trace_to[S: Hashable](
    parent: Mapping[Hashable, tuple[Hashable, str] | None],
    states_by_id: Mapping[Hashable, S],
    sid: Hashable,
) -> tuple[Step[S], ...]:
    """Walk the parent chain (by state IDENTITY) back to an initial state, then return it forward as Steps —
    each Step carrying the RICH state (looked up in ``states_by_id``), so a ``key`` identity never leaks in."""
    chain: list[Step[S]] = []
    cur: Hashable | None = sid
    while cur is not None:
        entry = parent.get(cur)
        state = states_by_id[cur]
        if entry is None:
            chain.append(Step(action="<init>", state=state))
            break
        prev, action = entry
        chain.append(Step(action=action, state=state))
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
    ``symmetry_reduction_sound`` before trusting it. Honours the model's ``actions_fn`` (per-state action
    list) when set. States must be HASHABLE here (they key the graph); ``check``/``check_all`` accept a
    ``key`` for non-hashable states, but the graph tools do not."""
    starts = model.initial_states()
    source = actions_source(model)
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
        for name, nxt in _successors(source, canon, state):
            out.append((name, nxt))
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


def reaches[S: Hashable](graph: Graph[S], predicate: Callable[[S], bool]) -> frozenset[S]:
    """The states of ``graph`` from which a ``predicate``-satisfying state is reachable (states
    already satisfying it included) — plain reachability, by BFS over the reversed edges.

    This is the *weaker* cousin of liveness: "can it still get there?", not "must it get there?".
    ``reaches(g, p) == set(g.states)`` says the goal stays available from every reachable state
    (in CTL terms: AG EF p) — e.g. "``fmi3FreeInstance`` is legal in every mode" — whereas
    ``check_liveness(..., everywhere=True)`` demands every run *actually* reach it (AG AF p): a
    cycle that forever declines an available exit toward p violates the latter, never the former.
    The complement ``set(graph.states) - reaches(graph, p)`` is the trap — reachable states from
    which p is already lost."""
    rev: dict[S, list[S]] = {s: [] for s in graph.states}
    for s in graph.states:
        for _a, t in graph.edges[s]:
            rev[t].append(s)
    seen = {s for s in graph.states if predicate(s)}
    frontier = list(seen)
    head = 0
    while head < len(frontier):
        s = frontier[head]
        head += 1
        for p in rev[s]:
            if p not in seen:
                seen.add(p)
                frontier.append(p)
    return frozenset(seen)


def _path_from_parents[S: Hashable](parent: Mapping[S, tuple[S, str] | None], target: S) -> tuple[Step[S], ...]:
    """Reconstruct the ``<init> -> ... -> target`` Step path from a BFS ``parent`` map (``None`` at a root)."""
    chain: list[Step[S]] = []
    cur: S = target
    while True:
        edge = parent[cur]
        if edge is None:
            chain.append(Step(action="<init>", state=cur))
            break
        prev, action = edge
        chain.append(Step(action=action, state=cur))
        cur = prev
    return tuple(reversed(chain))


def _shortest_step_path[S: Hashable](graph: Graph[S], goal: Callable[[S], bool]) -> tuple[Step[S], ...] | None:
    """Shortest path from an initial state to the first ``goal``-satisfying state, as a ``Step`` tuple
    (``<init>`` then one step per edge taken), or None if no reachable state satisfies ``goal``. Forward BFS
    over ``graph.edges``, so the returned path is of minimum length."""
    parent: dict[S, tuple[S, str] | None] = {}
    frontier: list[S] = []
    for s0 in graph.initial:
        if s0 not in parent:
            parent[s0] = None
            frontier.append(s0)
    head = 0
    while head < len(frontier):
        s = frontier[head]
        head += 1
        if goal(s):
            return _path_from_parents(parent, s)
        for name, t in graph.edges.get(s, ()):
            if t not in parent:
                parent[t] = (s, name)
                frontier.append(t)
    return None


def check_of[S: Hashable](graph: Graph[S], model: Model[S]) -> Result[S]:
    """Run the safety check over an ALREADY-explored ``graph`` instead of re-exploring — the graph-first
    counterpart to ``check`` (as ``coverage_of`` is to ``coverage``), so several analyses can share one
    ``explore``. Returns the same ``Result``: the first invariant violation or deadlock in breadth-first
    order (shortest trace), else OK.

    Deadlock detection needs a COMPLETE graph: on a truncated one a cut-off frontier state looks like a sink,
    so deadlocks are not reported there (invariant violations still are — a reachable violating state is a
    real bug regardless), and a clean result carries ``truncated=True`` (inconclusive). ``check(model)``
    equals ``check_of(explore(model), model)`` on a complete graph, but ``check`` keeps its early-exit (it
    stops at the first violation without building the whole graph), so prefer ``check`` when the verdict is
    all you need. ``states_explored`` is the whole graph here, not ``check``'s partial count at early-exit."""
    parent: dict[S, tuple[S, str] | None] = {}
    frontier: list[S] = []
    for s0 in graph.initial:
        if s0 not in parent:
            parent[s0] = None
            frontier.append(s0)
    total = len(graph.states)
    head = 0
    while head < len(frontier):
        state = frontier[head]
        head += 1
        for name, inv in model.invariants.items():
            verdict = inv(state)
            if isinstance(verdict, str):
                return Result(ok=False, states_explored=total, kind="invariant", invariant=name,
                              reason=verdict or None, trace=_path_from_parents(parent, state))
            if not verdict:
                return Result(ok=False, states_explored=total, kind="invariant", invariant=name,
                              trace=_path_from_parents(parent, state))
        out = graph.edges.get(state, ())
        if model.edge_invariants:
            for name, nxt in out:
                for iname, einv in model.edge_invariants.items():
                    verdict = einv(state, name, nxt)
                    if isinstance(verdict, str) or not verdict:
                        return Result(
                            ok=False, states_explored=total, kind="edge-invariant", invariant=iname,
                            reason=(verdict or None) if isinstance(verdict, str) else None,
                            trace=(*_path_from_parents(parent, state), Step(action=name, state=nxt)),
                        )
        if not out and not graph.truncated and not model.terminal(state):
            return Result(ok=False, states_explored=total, kind="deadlock", trace=_path_from_parents(parent, state))
        for name, t in out:
            if t not in parent:
                parent[t] = (state, name)
                frontier.append(t)
    return Result(ok=True, states_explored=total, truncated=graph.truncated)


def never[S: Hashable](action: str, *, when: Callable[[S], bool] | None = None) -> EdgeInvariant[S]:
    """An edge invariant that FORBIDS a transition: violated when ``action`` fires (optionally only from a
    ``when`` before-state). The direct way to rule out an illegal step without a ghost flag on the state,
    e.g. ``edge_invariants={"no-approve-unreviewed": never("approve", when=lambda s: not s.reviewed)}``."""

    def edge_inv(before: S, name: str, _after: S) -> bool:
        return not (name == action and (when is None or when(before)))

    return edge_inv


def path_to[S: Hashable](graph: Graph[S], state: S) -> tuple[Step[S], ...] | None:
    """The shortest path from an initial state to ``state`` (a specific reachable state), as a ``Step``
    tuple, or None if ``state`` is not reachable. The positive counterpart to a counterexample trace — a
    WITNESS that a state is reachable, and how. Render it with ``format_trace``."""
    return _shortest_step_path(graph, lambda s: s == state)


def witness[S: Hashable](graph: Graph[S], predicate: Callable[[S], bool]) -> tuple[Step[S], ...] | None:
    """The shortest path from an initial state to SOME reachable state satisfying ``predicate`` — a witness
    that a *good* state is reachable and how to get there — or None if none is. Where ``reaches`` answers the
    same question as a yes/no over the whole reachable set, this returns the concrete path. Render it with
    ``format_trace``."""
    return _shortest_step_path(graph, predicate)


def states_where[S: Hashable](graph: Graph[S], predicate: Callable[[S], bool]) -> tuple[S, ...]:
    """The reachable states of ``graph`` satisfying ``predicate``, in exploration order.
    ``solution_cardinality`` counts these; this returns them (e.g. to inspect *which* states a goal holds
    in, or feed to ``path_to``)."""
    return tuple(s for s in graph.states if predicate(s))


@dataclass(frozen=True, slots=True)
class FixedPoints[S: Hashable]:
    """Where the system settles: for each initial state, the distinct terminal states (no outgoing
    edge) reachable from it. Built by ``fixed_points``; ``confluent`` is the headline question."""

    by_init: Mapping[S, frozenset[S]]
    truncated: bool = False

    @property
    def confluent(self) -> bool:
        """True when every single initial state settles in at most one place — the fixed point does
        not depend on the order actions fired. A start with an *empty* set never settles at all (it
        can only loop); that is a liveness question, not a confluence one, and does not count
        against confluence. False whenever ``truncated`` (inconclusive)."""
        return not self.truncated and all(len(t) <= 1 for t in self.by_init.values())

    def __str__(self) -> str:
        if self.truncated:
            return "FIXED POINTS INCONCLUSIVE (truncated at max_states)"
        lines = [
            f"  {init} settles in {len(terms)} place(s)" for init, terms in self.by_init.items()
        ]
        head = "CONFLUENT" if self.confluent else "NOT CONFLUENT (an initial state has a choice)"
        return "\n".join([head, *lines])


def fixed_points[S: Hashable](
    model: Model[S],
    *,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
) -> FixedPoints[S]:
    """From each initial state separately: in which distinct terminal states can the runs end?
    One start that can settle in two different places means the outcome depends on the order
    actions fired — the bug this exists to catch (e.g. event iteration whose fixed point depends
    on which pending event is applied first). Per initial state on purpose: different starts are
    *allowed* to settle differently (that is what a latch is for); ``confluent`` only demands each
    single start settle in at most one place.

    Terminal here is structural — no outgoing edge — independent of ``model.terminal``: the
    question is where the dynamics stop, not which stops are declared legitimate. A start mapped
    to an empty set never settles (every path loops); ask ``check_liveness`` about that instead.
    ``canonicalize`` applies symmetry reduction (see ``check``). If any exploration hits
    ``max_states`` the result is inconclusive: ``truncated`` is set and ``confluent`` is False."""
    by_init: dict[S, frozenset[S]] = {}
    truncated = False
    for s0 in model.initial_states():
        g = explore(
            Model(init=(s0,), actions=model.actions),
            max_states=max_states,
            canonicalize=canonicalize,
        )
        truncated = truncated or g.truncated
        by_init[g.initial[0]] = frozenset(s for s in g.states if not g.edges[s])
    return FixedPoints(by_init=by_init, truncated=truncated)


def fixed_points_of[S: Hashable](graph: Graph[S]) -> FixedPoints[S]:
    """Graph-first ``fixed_points``: the per-initial structural fixed points over an ALREADY-explored
    ``graph`` instead of re-exploring from each initial — the graph-first counterpart to ``fixed_points`` (as
    ``check_of`` is to ``check``), so several analyses can share one ``explore``. For each initial state, the
    distinct STRUCTURAL terminals (a state with no outgoing edge) reachable from it, by forward BFS over the
    graph's edges.

    Equals ``fixed_points(model)`` on a graph built by ``explore(model)`` with the same ``canonicalize`` (the
    corpus pins this), and carries the graph's ``truncated`` — a truncated graph is inconclusive, so
    ``confluent`` is then False. Structural terminal is independent of ``model.terminal`` (the question is
    where the dynamics STOP, not which stops are declared legitimate), which is why this needs only the graph."""
    terminals = frozenset(s for s in graph.states if not graph.edges.get(s, ()))
    by_init: dict[S, frozenset[S]] = {}
    for s0 in graph.initial:
        seen = {s0}
        frontier = [s0]
        head = 0
        while head < len(frontier):
            state = frontier[head]
            head += 1
            for _name, t in graph.edges.get(state, ()):
                if t not in seen:
                    seen.add(t)
                    frontier.append(t)
        by_init[s0] = frozenset(s for s in seen if s in terminals)
    return FixedPoints(by_init=by_init, truncated=graph.truncated)


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


def footprint_sound[S: Hashable](model: Model[S], states: Iterable[S]) -> bool:
    """Sample-check a ``Model.footprint`` over the given ``states`` — the gate to pass before trusting
    the footprint memoization (see ``Model.footprint``).

    ``footprint`` is a performance cache, not a quotient: it does not change WHICH states are explored,
    only avoids re-running ``actions_fn`` for states that share a footprint. That makes it soundness-
    critical the other way round from ``canonicalize`` — an unsound footprint does not shrink the space,
    it hands a state the WRONG memoized menu, so the sweep follows wrong successors and can miss states
    (and the violations only they reach). The obligation is that ``actions_fn`` yields the SAME menu for
    any two states with equal ``footprint``.

    This groups ``states`` by ``footprint`` and returns False if any group holds two states whose
    ``actions_fn`` menus differ, compared by the MULTISET OF ACTION NAMES (so a footprint that changes an
    action's behaviour while keeping its name is out of scope — keep the name a faithful label). Returns
    False if the model has no ``actions_fn`` or ``footprint`` to validate. Pass a representative sample:
    for a hashable model, ``explore(model).states``; for a non-hashable one (a pydantic state checked via
    ``key=``, exactly footprint's target case), a hand-picked or generated set. Like every sampling gate
    it can only DISPROVE soundness on the states it sees, never prove it universally."""
    actions_fn = model.actions_fn
    footprint = model.footprint
    if actions_fn is None or footprint is None:
        return False
    menus: dict[Hashable, tuple[str, ...]] = {}
    for s in states:
        menu = tuple(sorted(a.name for a in actions_fn(s)))
        fp = footprint(s)
        if fp in menus:
            if menus[fp] != menu:
                return False
        else:
            menus[fp] = menu
    return True


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
