"""Linear Temporal Logic — a formula AST plus a checker.

The nodes (``Atom``, ``Not``, ``And``, ``Or``, ``Implies``, ``Next``, ``Eventually``, ``Always``,
``Until``, ``Release``, ``WeakUntil``) build an LTL formula as pure data. ``check_ltl`` checks ANY of them.

``check_ltl`` first tries the shapes that reduce SOUNDLY to musil's proven primitives (fast, and they
carry a shortest-path counterexample trace):

- ``Always(state)``                    -> a safety invariant (``check``)
- ``Eventually(state)``                -> ``<>P`` (``check_liveness``)
- ``Always(Eventually(state))``        -> ``[]<>P`` recurrence (``check_liveness(everywhere=True)``)
- ``Always(Implies(state, Eventually(state)))`` -> the response/leads-to property
- a top-level conjunction of any of the above (checked conjunct by conjunct)

where ``state`` is any boolean combination of ``Atom``s. Anything else — ``Next``, ``Until``, ``Release``,
``WeakUntil``, arbitrary nesting — falls through to the GENERAL engine: ``model |= phi`` iff the Büchi
automaton for ``Not(phi)`` (GPVW, ``GeneralizedBuchi.from_ltl``) has no accepting run over the
stutter-extended reachable graph (``has_accepting_run``, emptiness via SCC). The engine is sound over
infinite runs; terminal/deadlock states are stutter-extended so their finite runs are handled. Still to
come: a counterexample lasso from the engine, and re-expressing the fixed liveness forms / ``musil.patterns``
as sugar over ``check_ltl``. See ``LTL_NOTES.md``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, replace
from itertools import count

from musil.core import Graph, Model, Result, Step, check, explore
from musil.history import LastAction, action_taken, with_last_action
from musil.liveness import LivenessResult, check_liveness, has_internal_edge, tarjan


def _stutter[S: Hashable](graph: Graph[S]) -> Graph[S]:
    """Add a self-loop to every state with no successor, so a finite maximal run that would end there
    becomes an infinite stuttering run — LTL's semantics are over infinite runs, and the Büchi product
    only sees infinite runs (a dead-end product state is in no cycle). Returns a new ``Graph``."""
    edges: dict[S, tuple[tuple[str, S], ...]] = {}
    for s in graph.states:
        out = tuple(graph.edges.get(s, ()))
        edges[s] = out if out else (("<stutter>", s),)
    return replace(graph, edges=edges)


class LTL[S: Hashable]:
    """Base class for LTL formula nodes. Construct with the node classes below; check with ``check_ltl``."""


@dataclass(frozen=True, slots=True)
class Atom[S: Hashable](LTL[S]):
    """An atomic proposition: a named state predicate."""

    name: str
    predicate: Callable[[S], bool]

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Not[S: Hashable](LTL[S]):
    arg: LTL[S]

    def __str__(self) -> str:
        return f"!{self.arg}"


@dataclass(frozen=True, slots=True)
class And[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} & {self.right})"


@dataclass(frozen=True, slots=True)
class Or[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} | {self.right})"


@dataclass(frozen=True, slots=True)
class Implies[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} -> {self.right})"


@dataclass(frozen=True, slots=True)
class Next[S: Hashable](LTL[S]):
    arg: LTL[S]

    def __str__(self) -> str:
        return f"X {self.arg}"


@dataclass(frozen=True, slots=True)
class Eventually[S: Hashable](LTL[S]):
    arg: LTL[S]

    def __str__(self) -> str:
        return f"F {self.arg}"


@dataclass(frozen=True, slots=True)
class Always[S: Hashable](LTL[S]):
    arg: LTL[S]

    def __str__(self) -> str:
        return f"G {self.arg}"


@dataclass(frozen=True, slots=True)
class Until[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} U {self.right})"


@dataclass(frozen=True, slots=True)
class Release[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} R {self.right})"


@dataclass(frozen=True, slots=True)
class WeakUntil[S: Hashable](LTL[S]):
    left: LTL[S]
    right: LTL[S]

    def __str__(self) -> str:
        return f"({self.left} W {self.right})"


def _push_negations[S: Hashable](formula: LTL[S]) -> LTL[S]:
    """Push every ``Not`` down toward the atoms using LTL dualities (semantics-preserving): ``!!x = x``,
    ``!F x = G !x``, ``!G x = F !x``, ``!X x = X !x``, ``!(a & b) = !a | !b`` and its dual, ``!(a -> b) =
    a & !b``, ``!(a U b) = !a R !b`` and its dual, ``!(a W b) = !b U (!a & !b)``. ``Implies`` is kept as a
    node (not expanded to ``!a | b``) so the response shape ``G(a -> F b)`` survives for the reduction.
    This both widens the fragment ``check_ltl`` can reduce (negated temporal forms) and is the negation-
    normal-form preprocessing the general Büchi construction will need."""
    match formula:
        case Atom():
            return formula
        case Not(arg=inner):
            match inner:
                case Atom():
                    return formula  # a literal
                case Not(arg=x):
                    return _push_negations(x)
                case And(left=a, right=b):
                    return Or(_push_negations(Not(a)), _push_negations(Not(b)))
                case Or(left=a, right=b):
                    return And(_push_negations(Not(a)), _push_negations(Not(b)))
                case Implies(left=a, right=b):
                    return And(_push_negations(a), _push_negations(Not(b)))
                case Next(arg=x):
                    return Next(_push_negations(Not(x)))
                case Eventually(arg=x):
                    return Always(_push_negations(Not(x)))
                case Always(arg=x):
                    return Eventually(_push_negations(Not(x)))
                case Until(left=a, right=b):
                    return Release(_push_negations(Not(a)), _push_negations(Not(b)))
                case Release(left=a, right=b):
                    return Until(_push_negations(Not(a)), _push_negations(Not(b)))
                case WeakUntil(left=a, right=b):
                    nb = _push_negations(Not(b))
                    return Until(nb, And(_push_negations(Not(a)), nb))
                case _:
                    return formula
        case And(left=a, right=b):
            return And(_push_negations(a), _push_negations(b))
        case Or(left=a, right=b):
            return Or(_push_negations(a), _push_negations(b))
        case Implies(left=a, right=b):
            return Implies(_push_negations(a), _push_negations(b))
        case Next(arg=x):
            return Next(_push_negations(x))
        case Eventually(arg=x):
            return Eventually(_push_negations(x))
        case Always(arg=x):
            return Always(_push_negations(x))
        case Until(left=a, right=b):
            return Until(_push_negations(a), _push_negations(b))
        case Release(left=a, right=b):
            return Release(_push_negations(a), _push_negations(b))
        case WeakUntil(left=a, right=b):
            return WeakUntil(_push_negations(a), _push_negations(b))
        case _:
            return formula


def _state_predicate[S: Hashable](formula: LTL[S]) -> Callable[[S], bool] | None:
    """Compile a temporal-operator-free formula (a boolean combination of ``Atom``s) to a state
    predicate, or return None if it contains any temporal operator."""
    match formula:
        case Atom(predicate=p):
            return p
        case Not(arg=a):
            pa = _state_predicate(a)
            return None if pa is None else (lambda s, f=pa: not f(s))
        case And(left=lhs, right=rhs):
            pl, pr = _state_predicate(lhs), _state_predicate(rhs)
            return None if pl is None or pr is None else (lambda s, a=pl, b=pr: a(s) and b(s))
        case Or(left=lhs, right=rhs):
            pl, pr = _state_predicate(lhs), _state_predicate(rhs)
            return None if pl is None or pr is None else (lambda s, a=pl, b=pr: a(s) or b(s))
        case Implies(left=lhs, right=rhs):
            pl, pr = _state_predicate(lhs), _state_predicate(rhs)
            return None if pl is None or pr is None else (lambda s, a=pl, b=pr: (not a(s)) or b(s))
        case _:
            return None


def _lift_atom[S: Hashable](predicate: Callable[[S], bool]) -> Callable[[LastAction[S]], bool]:
    """Lift a predicate over ``S`` to one over ``LastAction[S]`` by reading the underlying ``.state``."""
    return lambda la: predicate(la.state)


def _lift_formula[S: Hashable](phi: LTL[S]) -> LTL[LastAction[S]]:
    """Rewrite a formula over ``S`` to the same formula over ``LastAction[S]``: every ``Atom`` reads the
    underlying ``.state``, the temporal/boolean structure is unchanged. Lets a state property be checked on
    the ``with_last_action``-augmented model."""
    match phi:
        case Atom(name=n, predicate=p):
            return Atom(n, _lift_atom(p))
        case Not(arg=a):
            return Not(_lift_formula(a))
        case And(left=lhs, right=rhs):
            return And(_lift_formula(lhs), _lift_formula(rhs))
        case Or(left=lhs, right=rhs):
            return Or(_lift_formula(lhs), _lift_formula(rhs))
        case Implies(left=lhs, right=rhs):
            return Implies(_lift_formula(lhs), _lift_formula(rhs))
        case Next(arg=a):
            return Next(_lift_formula(a))
        case Eventually(arg=a):
            return Eventually(_lift_formula(a))
        case Always(arg=a):
            return Always(_lift_formula(a))
        case Until(left=lhs, right=rhs):
            return Until(_lift_formula(lhs), _lift_formula(rhs))
        case Release(left=lhs, right=rhs):
            return Release(_lift_formula(lhs), _lift_formula(rhs))
        case WeakUntil(left=lhs, right=rhs):
            return WeakUntil(_lift_formula(lhs), _lift_formula(rhs))
        case _:  # pragma: no cover - the match is exhaustive over the AST
            raise TypeError(f"cannot lift unknown LTL node {type(phi).__name__}")


def _enabled_by_name[S: Hashable](model: Model[S], name: str) -> Callable[[S], bool]:
    """The predicate "some action named ``name`` is enabled at this state" over the ORIGINAL state — the
    ``enabled(a)`` side of a fairness premise. Honours ``actions_fn`` when set, else the static actions."""
    afn = model.actions_fn
    if afn is None:
        acts = tuple(a for a in model.actions if a.name == name)
        return lambda s: any(a.enabled(s) for a in acts)
    return lambda s: any(a.name == name and a.enabled(s) for a in afn(s))


def _fairness_premise[S: Hashable](
    model: Model[S], weak: list[str], strong: list[str]
) -> LTL[LastAction[S]]:
    """The fairness assumption as an LTL formula over the augmented model: the conjunction, over each fair
    action ``a``, of weak fairness ``FG enabled(a) -> GF taken(a)`` (i.e. ``GF !enabled(a) | GF taken(a)``)
    and strong fairness ``GF enabled(a) -> GF taken(a)`` (i.e. ``FG !enabled(a) | GF taken(a)``). On the
    ``with_last_action`` model ``taken(a)`` is the state atom ``action_taken(a)`` and ``enabled(a)`` reads the
    underlying state, so the whole premise is plain LTL the general engine already checks."""
    terms: list[LTL[LastAction[S]]] = []
    for kind, names in (("weak", weak), ("strong", strong)):
        for nm in names:
            enabled_pred = _enabled_by_name(model, nm)
            en: LTL[LastAction[S]] = Atom(f"enabled:{nm}", lambda la, _p=enabled_pred: _p(la.state))
            took: LTL[LastAction[S]] = Atom(f"taken:{nm}", action_taken(nm))
            gf_took = Always(Eventually(took))
            if kind == "weak":  # GF !enabled | GF taken
                terms.append(Or(Always(Eventually(Not(en))), gf_took))
            else:  # strong: FG !enabled | GF taken
                terms.append(Or(Eventually(Always(Not(en))), gf_took))
    premise = terms[0]
    for t in terms[1:]:
        premise = And(premise, t)
    return premise


def _check_ltl_fair[S: Hashable](
    model: Model[S], formula: LTL[S], weak: list[str], strong: list[str], *, max_states: int
) -> Result[S]:
    """Fair LTL by reduction: ``model |=_fair phi`` iff ``model |= (fairness -> phi)``. Encode the fairness
    assumption as an LTL premise over the ``with_last_action`` model (where ``taken``/``enabled`` are state
    atoms), lift ``phi`` onto that model, and run the general engine on ``premise -> phi``. A counterexample is
    a FAIR run violating ``phi``; its ``LastAction`` states are mapped back to the original states."""
    if model.actions_fn is None:  # validate names against the static action set (as check_liveness does)
        known = {a.name for a in model.actions}
        unknown = sorted({nm for nm in (*weak, *strong) if nm not in known})
        if unknown:
            raise ValueError(f"check_ltl: unknown fair action name(s) {unknown}; actions are {sorted(known)}")
    augmented = with_last_action(model)
    prop = Implies(_fairness_premise(model, weak, strong), _lift_formula(formula))
    graph = _stutter(explore(augmented, max_states=max_states))
    found = GeneralizedBuchi[LastAction[S]].from_ltl(Not(prop)).accepting_lasso(graph)
    if found is None:
        return Result(ok=True, states_explored=len(graph.states), truncated=graph.truncated)
    steps, loop = found
    trace = tuple(Step(action=s.action, state=s.state.state) for s in steps)
    return Result(
        ok=False,
        states_explored=len(graph.states),
        kind="ltl",
        reason=str(formula),
        trace=trace,
        loop=loop,
        truncated=graph.truncated,
    )


def check_ltl[S: Hashable](
    model: Model[S],
    formula: LTL[S],
    *,
    name: str = "ltl",
    fair: Iterable[str] | None = None,
    fair_strong: Iterable[str] | None = None,
    max_states: int = 1_000_000,
) -> Result[S] | LivenessResult[S]:
    """Check ``formula`` against ``model``, reducing the supported fragment onto ``check`` /
    ``check_liveness`` (see the module docstring). Returns a ``Result`` for the safety reductions and a
    ``LivenessResult`` for the liveness ones; both satisfy the ``Verdict`` protocol (``.ok`` + ``__str__``).
    ``fair`` / ``fair_strong`` (weak / strong fairness by action NAME) apply everywhere: the reducible forms
    (F / GF / G(a -> F b)) route through ``check_liveness``, and any other formula is checked by the general
    Büchi engine under fairness by reduction — ``model |=_fair phi`` iff ``model |= (fairness -> phi)``, with
    the fairness assumption encoded as an LTL premise over the ``with_last_action`` model (where ``taken(a)``
    and ``enabled(a)`` are state atoms). A counterexample is then a FAIR run violating ``phi``, its states
    mapped back to the model's own. An unknown fair action name raises ``ValueError`` (validated against the
    static action set). Any formula outside the reducible shapes is otherwise checked by the general engine
    over the stutter-extended reachable graph (a ``Result`` with ``kind="ltl"`` on violation). On violation the ``Result`` carries a counterexample trace: the accepting
    lasso of the ``Not(formula)`` automaton mapped back to model states — ``<init> -> ...(stem)... ->
    ...(cycle)`` — a concrete run that refutes the formula. Requires hashable states (the engine explores
    the graph)."""
    formula = _push_negations(formula)  # negated temporal forms become reducible; e.g. !F p -> G !p
    match formula:
        case Always(arg=Eventually(arg=inner)):  # G F inner -> recurrence []<>P
            p = _state_predicate(inner)
            if p is not None:
                return check_liveness(model, goal=p, everywhere=True, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
        case Always(arg=Implies(left=trigger, right=Eventually(arg=response))):  # G(a -> F b) -> response
            pa, pb = _state_predicate(trigger), _state_predicate(response)
            if pa is not None and pb is not None:
                return check_liveness(model, goal=pb, leadsto_from=pa, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
        case Always(arg=inner):  # G state -> safety invariant
            p = _state_predicate(inner)
            if p is not None:
                return check(replace(model, invariants={name: p}), max_states=max_states)
        case Eventually(arg=inner):  # F state -> <>P
            p = _state_predicate(inner)
            if p is not None:
                return check_liveness(model, goal=p, goal_name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
        case And(left=a, right=b):  # model |= (a & b) iff model |= a and model |= b (conjunction splits)
            left_result = check_ltl(model, a, name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
            if not left_result.ok:
                return left_result
            return check_ltl(model, b, name=name, fair=fair, fair_strong=fair_strong, max_states=max_states)
        case _:
            pass
    # Fairness on the general-engine path: reduce fair-LTL to plain LTL over the with_last_action model,
    # where taken(a)/enabled(a) are state atoms and the fairness assumption is an LTL premise (see
    # _check_ltl_fair and LTL_NOTES.md). Only the reducible forms above route through check_liveness.
    weak = list(fair) if fair is not None else []
    strong = list(fair_strong) if fair_strong is not None else []
    if weak or strong:
        return _check_ltl_fair(model, formula, weak, strong, max_states=max_states)
    # General engine: model |= phi iff the automaton for Not(phi) has no accepting run over the
    # (stutter-extended) reachable graph. Covers Until/Release/Next/arbitrary nesting.
    graph = _stutter(explore(model, max_states=max_states))
    found = GeneralizedBuchi[S].from_ltl(Not(formula)).accepting_lasso(graph)
    if found is None:
        return Result(ok=True, states_explored=len(graph.states), truncated=graph.truncated)
    steps, loop = found
    return Result(
        ok=False,
        states_explored=len(graph.states),
        kind="ltl",
        reason=str(formula),
        trace=steps,
        loop=loop,
        truncated=graph.truncated,
    )


def _product[S: Hashable](
    graph: Graph[S],
    initial: frozenset[int],
    transitions: Mapping[int, tuple[tuple[Callable[[S], bool], int], ...]],
) -> dict[tuple[S, int], list[tuple[str, tuple[S, int]]]]:
    """The reachable product of ``graph`` and an automaton (its ``initial`` states + guarded
    ``transitions``), as an adjacency map ``(m, q) -> [(action, (m', q')), ...]``. A product edge exists
    for each model edge ``m -> m'`` and automaton edge ``(guard, q')`` out of ``q`` with ``guard(m)`` true
    (the guard reads the SOURCE model state). Shared by ``Buchi`` and ``GeneralizedBuchi``."""
    prod: dict[tuple[S, int], list[tuple[str, tuple[S, int]]]] = {}
    frontier: list[tuple[S, int]] = []
    for m0 in graph.initial:
        for q0 in initial:
            start = (m0, q0)
            if start not in prod:
                prod[start] = []
                frontier.append(start)
    head = 0
    while head < len(frontier):
        m, q = frontier[head]
        head += 1
        outs = prod[(m, q)]
        edges = transitions.get(q, ())
        for action, m2 in graph.edges.get(m, ()):
            for guard, q2 in edges:
                if guard(m):
                    nxt = (m2, q2)
                    outs.append((action, nxt))
                    if nxt not in prod:
                        prod[nxt] = []
                        frontier.append(nxt)
    return prod


def _bfs_path[S: Hashable](
    prod: Mapping[tuple[S, int], list[tuple[str, tuple[S, int]]]],
    sources: set[tuple[S, int]],
    is_target: Callable[[tuple[S, int]], bool],
    allowed: set[tuple[S, int]] | None,
) -> tuple[list[tuple[str, tuple[S, int]]], tuple[S, int]] | None:
    """Shortest path in the product from any ``sources`` state to the first ``is_target`` state, staying
    within ``allowed`` (whole product if None). Returns ``(edges, source)`` where ``edges`` is the
    ``(action, next_state)`` list (empty if a source is already a target) and ``source`` is where it
    started, or None if no target is reachable."""
    parent: dict[tuple[S, int], tuple[tuple[S, int], str] | None] = {}
    queue: deque[tuple[S, int]] = deque()
    for s in sources:
        if s not in parent:
            parent[s] = None
            queue.append(s)
    while queue:
        u = queue.popleft()
        if is_target(u):
            edges: list[tuple[str, tuple[S, int]]] = []
            cur = u
            step = parent[cur]
            while step is not None:
                prev, action = step
                edges.append((action, cur))
                cur = prev
                step = parent[cur]
            edges.reverse()
            return edges, cur
        for action, v in prod.get(u, ()):
            if v not in parent and (allowed is None or v in allowed):
                parent[v] = (u, action)
                queue.append(v)
    return None


@dataclass(frozen=True, slots=True)
class Buchi[S: Hashable]:
    """A Büchi automaton over the alphabet of MODEL states — the sound back half of LTL model checking.

    Automaton states are ``int``s. ``transitions[q]`` is the tuple of ``(guard, q')`` edges out of ``q``,
    where ``guard(model_state)`` decides whether the edge fires from the model state currently being read
    (the SOURCE of each model step). A run of the automaton over a model run is ACCEPTING iff it visits an
    ``accepting`` automaton state infinitely often.

    Built by hand today (for testing the emptiness check); constructed from ``Not(formula)`` by the GPVW
    translation in a later step, at which point ``check_ltl`` runs it against ``explore(model)`` and an
    accepting run is a counterexample to the formula. See ``LTL_NOTES.md``."""

    initial: frozenset[int]
    accepting: frozenset[int]
    transitions: Mapping[int, tuple[tuple[Callable[[S], bool], int], ...]]

    def has_accepting_run(self, graph: Graph[S]) -> bool:
        """True iff the product of ``graph`` and this automaton has an accepting run: a cycle reachable
        from an initial product state that passes through an accepting automaton state. Emptiness via SCC
        (musil's proven ``tarjan``/``has_internal_edge``): an accepting run exists iff some reachable
        non-trivial SCC of the product contains a product state whose automaton component is accepting."""
        prod = _product(graph, self.initial, self.transitions)
        return any(
            has_internal_edge(scc, prod) and any(q in self.accepting for _m, q in scc)
            for scc in tarjan(set(prod), prod)
        )


@dataclass(frozen=True, slots=True)
class GeneralizedBuchi[S: Hashable]:
    """A GENERALIZED Büchi automaton: like ``Buchi`` but with SEVERAL acceptance sets. A run is accepting
    iff it visits EACH set in ``accepting_sets`` infinitely often. This is exactly the shape the GPVW
    construction produces from an LTL formula (one acceptance set per ``Until`` subformula), so the engine
    can run it directly without degeneralizing to a single-set ``Buchi``."""

    initial: frozenset[int]
    accepting_sets: tuple[frozenset[int], ...]
    transitions: Mapping[int, tuple[tuple[Callable[[S], bool], int], ...]]

    def has_accepting_run(self, graph: Graph[S]) -> bool:
        """True iff the product has a run visiting every acceptance set infinitely often. Emptiness via
        SCC: a reachable non-trivial SCC that intersects EVERY acceptance set contains such a run (being
        strongly connected, one cycle can visit all sets). With no acceptance sets, any non-trivial
        reachable SCC accepts (an unconstrained infinite run)."""
        prod = _product(graph, self.initial, self.transitions)
        return any(
            has_internal_edge(scc, prod)
            and all(any(q in acc for _m, q in scc) for acc in self.accepting_sets)
            for scc in tarjan(set(prod), prod)
        )

    def accepting_lasso(self, graph: Graph[S]) -> tuple[tuple[Step[S], ...], int] | None:
        """A concrete witness of an accepting run, as a lasso trace ``<init> -> ...(stem)... -> ...(cycle)``
        where the cycle repeats forever and visits every acceptance set, PLUS the index in that trace where
        the cycle begins (the state reached, then repeated forever). Returns None when there is no accepting
        run. Product states are mapped back to model states (the automaton component dropped); the looping
        cycle is appended once."""
        prod = _product(graph, self.initial, self.transitions)
        target: set[tuple[S, int]] | None = None
        for scc in tarjan(set(prod), prod):
            if has_internal_edge(scc, prod) and all(any(q in acc for _m, q in scc) for acc in self.accepting_sets):
                target = scc
                break
        if target is None:
            return None
        initial_prod = {(m0, q0) for m0 in graph.initial for q0 in self.initial if (m0, q0) in prod}
        found = _bfs_path(prod, initial_prod, lambda s: s in target, None)
        if found is None:
            return None
        stem, source = found
        entry = stem[-1][1] if stem else source
        cycle: list[tuple[str, tuple[S, int]]] = []
        current = entry
        for acc in self.accepting_sets:
            seg = _bfs_path(prod, {current}, lambda s, a=acc: s[1] in a, target)
            if seg is not None and seg[0]:
                cycle += seg[0]
                current = seg[0][-1][1]
        back = _bfs_path(prod, {current}, lambda s: s == entry, target)
        if back is not None:
            cycle += back[0]
        if not cycle:  # empty acceptance sets, or all already at entry: force one loop through the SCC
            for action, nxt in prod[entry]:
                if nxt in target:
                    ret = _bfs_path(prod, {nxt}, lambda s: s == entry, target)
                    cycle = [(action, nxt), *(ret[0] if ret is not None else [])]
                    break
        steps: list[Step[S]] = [Step(action="<init>", state=source[0])]
        steps += [Step(action=a, state=m) for a, (m, _q) in stem]
        steps += [Step(action=a, state=m) for a, (m, _q) in cycle]
        # index 0 is <init>, indices 1..len(stem) are the stem, so the cycle-entry state (repeated forever)
        # sits at index len(stem); the cycle steps follow it.
        return tuple(steps), len(stem)

    @classmethod
    def from_ltl(cls, formula: LTL[S]) -> GeneralizedBuchi[S]:
        """Build the automaton that accepts exactly the model runs satisfying ``formula``, via the GPVW
        (Gerth-Peled-Vardi-Wolper) tableau construction. To check ``model |= phi``, build the automaton for
        ``Not(phi)`` and ask whether it ``has_accepting_run(explore(model))`` — an accepting run is a
        counterexample to ``phi``. The formula is put in negation normal form first (``_push_negations``);
        each ``Until``/``Eventually`` subformula contributes one acceptance set (its eventuality must be
        fulfilled, not deferred forever). See ``LTL_NOTES.md``."""
        return _gpvw(formula)


@dataclass(slots=True)
class _GNode[S: Hashable]:
    """A GPVW tableau node: ``old`` are the subformulas that must hold at this node (its label),
    ``nextf`` the subformulas that must hold at every successor, ``incoming`` the predecessor node ids."""

    id: int
    incoming: set[int]
    old: frozenset[LTL[S]]
    nextf: frozenset[LTL[S]]


def _negate_literal[S: Hashable](literal: LTL[S]) -> LTL[S]:
    match literal:
        case Not(arg=inner):
            return inner
        case _:
            return Not(literal)


def _label_guard[S: Hashable](old: frozenset[LTL[S]]) -> Callable[[S], bool]:
    """The guard for a node: the model state must satisfy every literal (``Atom`` / ``Not(Atom)``) in
    ``old``. Non-literal formulas in ``old`` are structural obligations already discharged by expansion and
    impose no state constraint here."""
    lits: list[tuple[Callable[[S], bool], bool]] = []
    for f in old:
        match f:
            case Atom(predicate=p):
                lits.append((p, True))
            case Not(arg=Atom(predicate=p)):
                lits.append((p, False))
            case _:
                pass

    def guard(s: S) -> bool:
        return all(pred(s) == want for pred, want in lits)

    return guard


def _closure[S: Hashable](formula: LTL[S]) -> set[LTL[S]]:
    """Every subformula of ``formula`` (itself included)."""
    result: set[LTL[S]] = {formula}
    match formula:
        case Atom():
            pass
        case Not(arg=a) | Next(arg=a) | Eventually(arg=a) | Always(arg=a):
            result |= _closure(a)
        case (
            And(left=a, right=b)
            | Or(left=a, right=b)
            | Implies(left=a, right=b)
            | Until(left=a, right=b)
            | Release(left=a, right=b)
            | WeakUntil(left=a, right=b)
        ):
            result |= _closure(a) | _closure(b)
        case _:
            pass
    return result


def _eventualities[S: Hashable](formula: LTL[S]) -> list[tuple[LTL[S], LTL[S]]]:
    """The ``(subformula, fulfiller)`` pairs whose eventuality must not be deferred forever: each
    ``Until(a, b)`` promises ``b``, each ``Eventually(a)`` promises ``a``. (``Release``/``WeakUntil``/
    ``Always`` carry no such promise.)"""
    pairs: list[tuple[LTL[S], LTL[S]]] = []
    for sub in _closure(formula):
        match sub:
            case Until(right=b):
                pairs.append((sub, b))
            case Eventually(arg=a):
                pairs.append((sub, a))
            case _:
                pass
    return pairs


def _gpvw[S: Hashable](formula: LTL[S]) -> GeneralizedBuchi[S]:
    """The GPVW tableau construction: ``formula`` -> a generalized Büchi automaton accepting exactly its
    satisfying model runs. See ``LTL_NOTES.md`` and ``GeneralizedBuchi.from_ltl``."""
    phi = _push_negations(formula)
    finished: list[_GNode[S]] = []
    ids = count()
    init = -1  # sentinel "before the first node" predecessor

    def expand(new: frozenset[LTL[S]], old: frozenset[LTL[S]], nextf: frozenset[LTL[S]], incoming: frozenset[int]) -> None:
        if not new:
            for nd in finished:
                if nd.old == old and nd.nextf == nextf:
                    nd.incoming |= incoming
                    return
            node_id = next(ids)
            finished.append(_GNode(id=node_id, incoming=set(incoming), old=old, nextf=nextf))
            expand(nextf, frozenset(), frozenset(), frozenset({node_id}))
            return
        f = next(iter(new))
        rest = new - {f}
        if f in old:
            expand(rest, old, nextf, incoming)
            return
        match f:
            case Atom() | Not(arg=Atom()):
                if _negate_literal(f) in old:
                    return  # contradictory node — discard
                expand(rest, old | {f}, nextf, incoming)
            case And(left=a, right=b):
                expand(rest | ({a, b} - old), old | {f}, nextf, incoming)
            case Or(left=a, right=b):
                expand(rest | ({a} - old), old | {f}, nextf, incoming)
                expand(rest | ({b} - old), old | {f}, nextf, incoming)
            case Next(arg=a):
                expand(rest, old | {f}, nextf | {a}, incoming)
            case Until(left=a, right=b):  # a U b = b | (a & X(a U b))
                expand(rest | ({b} - old), old | {f}, nextf, incoming)
                expand(rest | ({a} - old), old | {f}, nextf | {f}, incoming)
            case Release(left=a, right=b):  # a R b = b & (a | X(a R b))
                expand(rest | ({a, b} - old), old | {f}, nextf, incoming)
                expand(rest | ({b} - old), old | {f}, nextf | {f}, incoming)
            case Eventually(arg=a):  # F a = a | X(F a)
                expand(rest | ({a} - old), old | {f}, nextf, incoming)
                expand(rest, old | {f}, nextf | {f}, incoming)
            case Always(arg=a):  # G a = a & X(G a)
                expand(rest | ({a} - old), old | {f}, nextf | {f}, incoming)
            case WeakUntil(left=a, right=b):  # a W b = b | (a & X(a W b))
                expand(rest | ({b} - old), old | {f}, nextf, incoming)
                expand(rest | ({a} - old), old | {f}, nextf | {f}, incoming)
            case _:
                expand(rest, old | {f}, nextf, incoming)

    expand(frozenset({phi}), frozenset(), frozenset(), frozenset({init}))

    initial = frozenset(nd.id for nd in finished if init in nd.incoming)
    transitions: dict[int, tuple[tuple[Callable[[S], bool], int], ...]] = {}
    for q in finished:
        guard = _label_guard(q.old)
        transitions[q.id] = tuple((guard, qp.id) for qp in finished if q.id in qp.incoming)
    accepting_sets = tuple(
        frozenset(nd.id for nd in finished if (mu not in nd.old) or (fulfiller in nd.old))
        for mu, fulfiller in _eventualities(phi)
    )
    return GeneralizedBuchi(initial=initial, accepting_sets=accepting_sets, transitions=transitions)
