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
weakly-fair non-trivial SCC. Dependency-free; for finite (bounded) models."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass

from musil.core import Graph, Model, Step, explore, format_trace


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
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    everywhere: bool = False,
    leadsto_from: Callable[[S], bool] | None = None,
    goal_name: str = "goal",
    max_states: int = 1_000_000,
) -> LivenessResult[S]:
    """Prove a liveness property and return a lasso counterexample if it fails.

    Default (``everywhere=False``) checks ``<>P`` — *eventually* P on every run from an initial
    state. ``everywhere=True`` checks ``[]<>P`` — *always eventually* P, i.e. from EVERY reachable
    state P is still eventually reached (the system always re-converges; no reachable stale cycle).
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
    weak fairness cannot."""
    g = explore(model, max_states=max_states)
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
    can_reach_goal = _backward_reachable_to_goal(g, goal)

    # (1) a reachable ¬P state from which P can never be reached — unconditional violation.
    for s in order:  # BFS order → shortest stem
        if s not in can_reach_goal:
            return LivenessResult(
                ok=False, states_explored=len(g.states), goal=goal_name,
                kind="p-unreachable", stem=_stem(parent, s),
            )

    # (2) a weakly-fair recurring cycle of ¬P states.
    for scc in _tarjan(reachable_bad, bad_succ):
        if not _has_internal_edge(scc, bad_succ):
            continue
        if _fair_admissible(scc, g.edges, fairset, strongset):
            entry = next(s for s in order if s in scc)  # shortest-stem entry
            return LivenessResult(
                ok=False, states_explored=len(g.states), goal=goal_name, kind="fair-cycle",
                stem=_stem(parent, entry), cycle=_simple_cycle(scc, entry, bad_succ),
            )

    return LivenessResult(ok=True, states_explored=len(g.states), goal=goal_name, truncated=g.truncated)


def _backward_reachable_to_goal[S: Hashable](g: Graph[S], goal: Callable[[S], bool]) -> set[S]:
    """States from which some goal state is reachable (goal states included)."""
    rev: dict[S, list[S]] = {s: [] for s in g.states}
    for s in g.states:
        for _a, t in g.edges[s]:
            rev[t].append(s)
    seen = {s for s in g.states if goal(s)}
    frontier = list(seen)
    head = 0
    while head < len(frontier):
        s = frontier[head]
        head += 1
        for p in rev[s]:
            if p not in seen:
                seen.add(p)
                frontier.append(p)
    return seen


def _has_internal_edge[S: Hashable](scc: set[S], succ: Mapping[S, list[tuple[str, S]]]) -> bool:
    """A non-trivial recurring set: >1 node, or a single node with a self-loop."""
    if len(scc) > 1:
        return True
    (only,) = tuple(scc)
    return any(t == only for _a, t in succ[only])


def _fair_admissible[S: Hashable](
    scc: set[S],
    edges: Mapping[S, tuple[tuple[str, S], ...]],
    weak: frozenset[str],
    strong: frozenset[str],
) -> bool:
    """Can the system loop in this SCC forever without violating the fairness assumptions? It cannot
    (so the loop is NOT a genuine counterexample) if any fair action must fire:
      - weak fairness: an action enabled in *every* SCC state but never taken on an internal edge;
      - strong fairness: an action enabled in *any* SCC state but never taken on an internal edge.
    Strong is the stronger requirement (enabled-somewhere is easier to meet than enabled-everywhere),
    so it rules out more cycles."""

    def taken_inside(a: str) -> bool:
        return any(name == a and t in scc for s in scc for name, t in edges[s])

    for a in weak:
        if not taken_inside(a) and all(any(name == a for name, _t in edges[s]) for s in scc):
            return False
    for a in strong:
        if not taken_inside(a) and any(any(name == a for name, _t in edges[s]) for s in scc):
            return False
    return True


def _tarjan[S: Hashable](nodes: set[S], succ: Mapping[S, list[tuple[str, S]]]) -> list[set[S]]:
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
