"""Liveness: does the system *eventually* reach a goal, or can it loop forever short of it?

``check_liveness(model, goal=P)`` proves the temporal property "eventually P" (<>P): on every run
from an initial state, P holds at some point. It fails in exactly two ways, and we report whichever
we find with a lasso counterexample (a stem into a recurring set, plus the loop):

  - **P unreachable** — a reachable state from which P can never be reached (a dead end or a trap
    SCC with no exit to P). No scheduling fixes this.
  - **fair cycle** — a reachable cycle of ¬P states that the system can follow forever. Whether
    this counts depends on FAIRNESS: under *weak fairness* of an action set, an action that is
    *continuously enabled* along the cycle must eventually be taken — so a cycle that starves a
    continuously-enabled fair action is not a real counterexample (the fair scheduler would break
    it). Pass ``fair=[...]`` to rule those out; with ``fair=()`` you get strict (no-fairness)
    liveness.

Method: explore the reachable graph, restrict to ¬P states reachable through ¬P from a ¬P initial
state, then (1) flag any from which P is unreachable, (2) Tarjan-SCC the rest and report the first
non-trivial SCC that hosts a fair cycle. *Strong* fairness (``fair_strong=[...]``: an action enabled
*infinitely often* must be taken) is checked with sub-SCC refinement — a strongly-fair action enabled
somewhere in an SCC but never taken need not fire on a cycle that avoids the states enabling it, so
those states are removed and the remainder re-decomposed to a fixpoint (Emerson-Lei). Without that,
a fair cycle confined to a sub-SCC is missed and the property is wrongly reported to hold.
Dependency-free; for finite (bounded) models."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass

from musil.core import Graph, Model, Step, explore, format_trace, reaches


@dataclass(frozen=True, slots=True)
class LivenessResult[S: Hashable]:
    """Outcome of an "eventually P" check. ``ok`` True means every run reaches P. Otherwise ``kind``
    is ``"p-unreachable"`` or ``"fair-cycle"``; ``stem`` is the shortest path from an initial state
    to the offending state, and ``cycle`` is the recurring loop (empty for a P-unreachable sink)."""

    ok: bool
    states_explored: int
    goal: str = "goal"
    kind: str | None = None
    stem: tuple[Step[S], ...] = ()
    cycle: tuple[Step[S], ...] = ()
    truncated: bool = False

    @property
    def action_names(self) -> tuple[str, ...]:
        """The action names along the counterexample — the ``stem`` into the offending state then the
        ``cycle`` it loops on — excluding the synthetic ``<init>`` step (empty on success)."""
        return tuple(step.action for step in (*self.stem, *self.cycle) if step.action != "<init>")

    @property
    def witness(self) -> S | None:
        """The offending state — the last state of the ``stem`` (the P-unreachable trap, or the entry of the
        fair cycle) — or None on success / an empty stem."""
        return self.stem[-1].state if self.stem else None

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            cap = " (TRUNCATED at cap)" if self.truncated else ""
            return f"OK — eventually '{self.goal}' on every run ({self.states_explored} states){cap}"
        if self.kind == "p-unreachable":
            return (
                f"LIVENESS VIOLATED: '{self.goal}' is unreachable from a reachable state\n"
                f"{format_trace(self.stem)}\n({self.states_explored} states explored)"
            )
        loop = "\n".join(f"  ↺ {s.action}: {s.state}" for s in self.cycle)
        return (
            f"LIVENESS VIOLATED: a fair cycle never reaches '{self.goal}'\n"
            f"{format_trace(self.stem)}\n  --- loops forever ---\n{loop}\n"
            f"({self.states_explored} states explored)"
        )


def check_liveness[S: Hashable](
    model: Model[S],
    *,
    goal: Callable[[S], bool],
    fair: Iterable[str] | None = None,
    fair_strong: Iterable[str] | None = None,
    everywhere: bool = False,
    leadsto_from: Callable[[S], bool] | None = None,
    goal_name: str = "goal",
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Prove a liveness property and return a lasso counterexample if it fails.

    Default (``everywhere=False``) checks ``<>P`` — *eventually* P on every run from an initial
    state. ``everywhere=True`` checks ``[]<>P`` — on every run, *always eventually* P: past any
    point of any run, P must actually be reached again. This is NOT reachability: a reachable
    cycle that forever declines to move toward P is a violation even when P stays reachable from
    every state on it — declare the exit in ``fair=[...]`` if a fair scheduler would eventually
    take it. For the weaker "P merely remains reachable from every state" (AG EF, no state is ever
    *trapped*), use ``reaches``: ``reaches(g, goal) == set(g.states)`` with ``g = explore(model)``.
    Use ``everywhere=True`` for convergence/recurrence properties whose model may start already
    satisfying P.

    ``leadsto_from=Q`` checks the **response** property ``[](Q -> <>P)`` — *whenever Q holds, P
    eventually follows*. This is the untimed "no resource gets stuck" property: e.g. every service
    that enters ``placed`` eventually reaches ``running`` or ``failed``. It is weaker than
    ``everywhere=True`` — only states triggered by Q must reach P, so a ¬P cycle that no Q-state can
    reach is not a violation. (Implemented by seeding the same analysis from every reachable Q∧¬P
    state; ``everywhere`` is ignored when ``leadsto_from`` is given.)

    Fairness prunes cycles a fair scheduler would break. ``fair`` = weak fairness (an action
    *continuously* enabled along a cycle must eventually be taken). ``fair_strong`` = strong fairness
    (an action enabled *infinitely often* — i.e. in any state of the cycle — must be taken); strong
    is the stronger assumption and rules out more cycles, so it can force a "flickering" action that
    weak fairness cannot.

    Each of ``fair`` / ``fair_strong`` is a tuple of action NAMES, OR left as ``None`` (the default) to
    DERIVE the set from the actions' own ``fair="weak"`` / ``fair="strong"`` tags — so the fair-ours /
    unfair-faults split lives on the actions, not in a parallel list kept in sync by hand. An explicit tuple
    is validated: a name matching no action raises ``ValueError`` (a silent no-match fails in the unsound
    direction). Tags and validation apply to a static ``actions`` list; with ``actions_fn`` pass names
    explicitly (they are then used unchecked)."""
    weak, strong = _resolve_fairness(model, fair, fair_strong)
    return check_liveness_of(
        explore(model, max_states=max_states),
        goal=goal,
        fair=weak,
        fair_strong=strong,
        everywhere=everywhere,
        leadsto_from=leadsto_from,
        goal_name=goal_name,
    )


def _resolve_fairness[S: Hashable](
    model: Model[S], fair: Iterable[str] | None, fair_strong: Iterable[str] | None
) -> tuple[frozenset[str], frozenset[str]]:
    """Resolve the weak / strong fair action-name sets for ``check_liveness``. ``None`` DERIVES a set from
    the actions' ``fair`` tags; an explicit iterable is used as given but VALIDATED — a name matching no
    action raises, since a fairness name that silently matches nothing fails in the UNSOUND direction (an
    action that should be fair is treated as unfair, or a filter accidentally grants fairness). Tags and
    validation apply to a STATIC action list only; with ``actions_fn`` the names cannot be enumerated
    statically, so an explicit set is used unchecked and ``None`` yields the empty set."""
    if model.actions_fn is not None:
        return frozenset(fair or ()), frozenset(fair_strong or ())
    actions = list(model.actions)
    names = {a.name for a in actions}
    weak = frozenset(fair) if fair is not None else frozenset(a.name for a in actions if a.fair == "weak")
    strong = (
        frozenset(fair_strong) if fair_strong is not None else frozenset(a.name for a in actions if a.fair == "strong")
    )
    if fair is not None and (unknown := weak - names):
        raise ValueError(f"check_liveness: fair names {sorted(unknown)} match no action (known: {sorted(names)})")
    if fair_strong is not None and (unknown := strong - names):
        raise ValueError(
            f"check_liveness: fair_strong names {sorted(unknown)} match no action (known: {sorted(names)})"
        )
    return weak, strong


def check_liveness_of[S: Hashable](
    graph: Graph[S],
    *,
    goal: Callable[[S], bool],
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    everywhere: bool = False,
    leadsto_from: Callable[[S], bool] | None = None,
    goal_name: str = "goal",
) -> LivenessResult[S]:
    """Run the liveness analysis over an ALREADY-explored ``graph`` instead of re-exploring — the graph-first
    counterpart to ``check_liveness`` (as ``coverage_of`` is to ``coverage``), so several analyses can share
    one ``explore``. Same properties, verdict, and lasso counterexample; see ``check_liveness`` for the full
    semantics of ``goal`` / ``everywhere`` / ``leadsto_from`` and the fairness assumptions. ``check_liveness``
    is exactly ``check_liveness_of(explore(model, max_states=max_states), ...)``."""
    g = graph
    fairset = frozenset(fair)
    strongset = frozenset(fair_strong)

    bad = {s for s in g.states if not goal(s)}
    if not bad:
        return LivenessResult(ok=True, states_explored=len(g.states), goal=goal_name, truncated=g.truncated)

    if leadsto_from is not None:
        # [](Q -> <>P): a violating run holds Q at some point, then stays ¬P forever. Every such run
        # has a witnessing reachable Q∧¬P state; seed from all of them and stay within ¬P (once P is
        # hit the obligation is discharged). Same ¬P-subgraph analysis as <>P, different seed.
        triggers = [s for s in g.states if s in bad and leadsto_from(s)]
        if not triggers:
            return LivenessResult(ok=True, states_explored=len(g.states), goal=goal_name, truncated=g.truncated)
        parent, order = _bfs(triggers, lambda s: [(a, t) for (a, t) in g.edges[s] if t in bad])
        reachable_bad = set(order)
    elif everywhere:
        # []<>P: a violating run may start anywhere, so seed from EVERY reachable ¬P state and take
        # stems over the full graph (the prefix may pass through P states before entering a stale cycle).
        parent, order_all = _bfs(g.initial, lambda s: g.edges[s])
        order = [s for s in order_all if s in bad]
        reachable_bad = set(bad)
    else:
        # <>P: a violating run is ¬P throughout, so seed from ¬P inits and stay within ¬P.
        bad_inits = [s for s in g.initial if s in bad]
        if not bad_inits:
            return LivenessResult(ok=True, states_explored=len(g.states), goal=goal_name, truncated=g.truncated)
        parent, order = _bfs(bad_inits, lambda s: [(a, t) for (a, t) in g.edges[s] if t in bad])
        reachable_bad = set(order)

    bad_succ: dict[S, list[tuple[str, S]]] = {
        s: [(a, t) for (a, t) in g.edges[s] if t in reachable_bad] for s in reachable_bad
    }
    can_reach_goal = reaches(g, goal)

    # (1) a reachable ¬P state from which P can never be reached — unconditional violation.
    for s in order:  # BFS order → shortest stem
        if s not in can_reach_goal:
            return LivenessResult(
                ok=False, states_explored=len(g.states), goal=goal_name,
                kind="p-unreachable", stem=_stem(parent, s),
            )

    # (2) a fair recurring cycle of ¬P states (strong fairness refines into sub-SCCs, see _find_fair_scc).
    fair_scc = _find_fair_scc(reachable_bad, bad_succ, g.edges, fairset, strongset)
    if fair_scc is not None:
        entry = next(s for s in order if s in fair_scc)  # shortest-stem entry
        return LivenessResult(
            ok=False, states_explored=len(g.states), goal=goal_name, kind="fair-cycle",
            stem=_stem(parent, entry), cycle=_simple_cycle(fair_scc, entry, bad_succ),
        )

    return LivenessResult(ok=True, states_explored=len(g.states), goal=goal_name, truncated=g.truncated)


def has_internal_edge[S: Hashable](scc: set[S], succ: Mapping[S, list[tuple[str, S]]]) -> bool:
    """A non-trivial recurring set: >1 node, or a single node with a self-loop."""
    if len(scc) > 1:
        return True
    (only,) = tuple(scc)
    return any(t == only for _a, t in succ[only])


def _taken_inside[S: Hashable](a: str, scc: set[S], edges: Mapping[S, tuple[tuple[str, S], ...]]) -> bool:
    """Whether action ``a`` labels an edge that stays inside ``scc`` (a fair action taken on the cycle)."""
    return any(name == a and t in scc for s in scc for name, t in edges[s])


def _enables[S: Hashable](a: str, s: S, edges: Mapping[S, tuple[tuple[str, S], ...]]) -> bool:
    """Whether action ``a`` is enabled at ``s`` (it labels some outgoing edge in the full graph)."""
    return any(name == a for name, _t in edges[s])


def _find_fair_scc[S: Hashable](
    states: set[S],
    bad_succ: Mapping[S, list[tuple[str, S]]],
    edges: Mapping[S, tuple[tuple[str, S], ...]],
    weak: frozenset[str],
    strong: frozenset[str],
) -> set[S] | None:
    """A non-trivial SCC within ``states`` (over the ¬P subgraph ``bad_succ``) that hosts a cycle satisfying
    the fairness assumptions, or None — the search for a fair counterexample cycle.

    A cycle is ruled out when a fair action *must* fire on it:

    - **Weak fairness**: an action enabled in EVERY state of the SCC but never taken inside must eventually
      fire. No cycle in the SCC (nor in any subset, which keeps it enabled everywhere) is fair, so the SCC
      is skipped outright.
    - **Strong fairness**: an action enabled in ANY state of the SCC but never taken inside must fire *if it
      stays enabled infinitely often* — but a cycle that AVOIDS the states where it is enabled never enables
      it, so it carries no obligation. So instead of rejecting the whole SCC (the old bug: a fair cycle
      confined to a sub-SCC was missed, wrongly reporting the property holds), remove the states that enable
      the action and re-decompose the remainder, recursing to a fixpoint (Emerson-Lei fair-cycle detection).

    Only when no fair action forces itself does the SCC host a fair cycle."""
    for scc in tarjan(states, bad_succ):
        if not has_internal_edge(scc, bad_succ):
            continue
        if any(
            not _taken_inside(a, scc, edges) and all(_enables(a, s, edges) for s in scc) for a in weak
        ):
            continue  # a weakly-fair action is enabled throughout and never taken: no fair cycle here
        forced = next(
            (a for a in strong if not _taken_inside(a, scc, edges) and any(_enables(a, s, edges) for s in scc)),
            None,
        )
        if forced is None:
            return scc  # no fair action forces itself: this SCC hosts a fair cycle
        # A strongly-fair action is enabled somewhere but never taken. Any fair cycle must avoid the states
        # that enable it (it is never taken here), so drop them and look for a fair cycle in the remainder.
        sub = _find_fair_scc(
            {s for s in scc if not _enables(forced, s, edges)}, bad_succ, edges, weak, strong
        )
        if sub is not None:
            return sub
    return None


def tarjan[S: Hashable](nodes: set[S], succ: Mapping[S, list[tuple[str, S]]]) -> list[set[S]]:
    """Iterative Tarjan SCC over the subgraph induced by ``nodes`` (successors outside ``nodes`` are
    ignored). Iterative to avoid Python recursion limits on deep graphs."""
    index: dict[S, int] = {}
    low: dict[S, int] = {}
    on_stack: set[S] = set()
    stack: list[S] = []
    sccs: list[set[S]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        # work stack of (node, successor-iterator)
        work: list[tuple[S, int]] = [(root, 0)]
        succ_list: dict[S, list[S]] = {}
        while work:
            v, i = work[-1]
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
                succ_list[v] = [t for _a, t in succ[v] if t in nodes]
            if i < len(succ_list[v]):
                work[-1] = (v, i + 1)
                w = succ_list[v][i]
                if w not in index:
                    work.append((w, 0))
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            else:
                if low[v] == index[v]:
                    comp: set[S] = set()
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.add(w)
                        if w == v:
                            break
                    sccs.append(comp)
                work.pop()
                if work:
                    parent_v = work[-1][0]
                    low[parent_v] = min(low[parent_v], low[v])
    return sccs


def _bfs[S: Hashable](
    starts: Iterable[S], succ: Callable[[S], Iterable[tuple[str, S]]]
) -> tuple[dict[S, tuple[S, str] | None], list[S]]:
    """BFS from ``starts`` over ``succ``; returns (parent map for trace reconstruction, visit order
    — which is by increasing distance, so it yields shortest stems)."""
    parent: dict[S, tuple[S, str] | None] = {}
    order: list[S] = []
    for s in starts:
        if s not in parent:
            parent[s] = None
            order.append(s)
    head = 0
    while head < len(order):
        s = order[head]
        head += 1
        for a, t in succ(s):
            if t not in parent:
                parent[t] = (s, a)
                order.append(t)
    return parent, order


def _stem[S: Hashable](parent: Mapping[S, tuple[S, str] | None], state: S) -> tuple[Step[S], ...]:
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


def _simple_cycle[S: Hashable](
    scc: set[S], entry: S, succ: Mapping[S, list[tuple[str, S]]]
) -> tuple[Step[S], ...]:
    """Shortest loop from ``entry`` back to ``entry`` within the SCC (BFS over internal edges)."""
    parent: dict[S, tuple[S, str]] = {}
    frontier: list[S] = []
    for a, t in succ[entry]:
        if t in scc and t not in parent:
            parent[t] = (entry, a)
            frontier.append(t)
            if t == entry:  # a self-loop
                return (Step(action=a, state=entry),)
    head = 0
    while head < len(frontier):
        s = frontier[head]
        head += 1
        for a, t in succ[s]:
            if t not in scc:
                continue
            if t == entry:
                steps = [Step(action=a, state=entry)]
                cur = s
                while cur != entry:
                    pv, pa = parent[cur]
                    steps.append(Step(action=pa, state=cur))
                    cur = pv
                steps.reverse()
                return tuple(steps)
            if t not in parent:
                parent[t] = (s, a)
                frontier.append(t)
    return ()
