"""Linear Temporal Logic — a formula AST plus a checker.

The nodes (``Atom``, ``Not``, ``And``, ``Or``, ``Implies``, ``Next``, ``Eventually``, ``Always``,
``Until``, ``Release``, ``WeakUntil``) build an LTL formula as pure data. ``check_ltl`` checks it.

This first layer checks the fragment that reduces SOUNDLY to musil's existing proven primitives:

- ``Always(state)``                    -> a safety invariant (``check``)
- ``Eventually(state)``                -> ``<>P`` (``check_liveness``)
- ``Always(Eventually(state))``        -> ``[]<>P`` recurrence (``check_liveness(everywhere=True)``)
- ``Always(Implies(state, Eventually(state)))`` -> the response/leads-to property

where ``state`` is any boolean combination of ``Atom``s (no temporal operator). Anything OUTSIDE this
fragment — ``Next``, ``Until``, ``Release``, ``WeakUntil``, or temporal nesting other than the shapes
above — raises ``NotImplementedError`` rather than returning a guessed verdict. The general engine (a
Büchi automaton for ``Not(formula)``, its product with the reachable graph, emptiness via nested-DFS)
lands incrementally on top of this same AST; when it does, the fixed liveness forms and ``musil.patterns``
become sugar over it.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass, replace

from musil.core import Graph, Model, Result, check
from musil.liveness import LivenessResult, check_liveness, has_internal_edge, tarjan


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


def check_ltl[S: Hashable](
    model: Model[S],
    formula: LTL[S],
    *,
    name: str = "ltl",
    fair: Iterable[str] = (),
    fair_strong: Iterable[str] = (),
    max_states: int = 1_000_000,
) -> Result[S] | LivenessResult[S]:
    """Check ``formula`` against ``model``, reducing the supported fragment onto ``check`` /
    ``check_liveness`` (see the module docstring). Returns a ``Result`` for the safety reductions and a
    ``LivenessResult`` for the liveness ones; both satisfy the ``Verdict`` protocol (``.ok`` + ``__str__``).
    ``fair`` / ``fair_strong`` apply to the liveness reductions. Raises ``NotImplementedError`` for any
    formula outside the fragment, never a guessed verdict."""
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
    raise NotImplementedError(
        f"check_ltl cannot yet check {formula!s}: it is outside the fragment reducible to check/"
        "check_liveness (G(state), F(state), G F(state), G(a -> F b)). The general Büchi + nested-DFS "
        "engine that covers Until/Release/Next/arbitrary nesting lands in a later step; until then this "
        "refuses rather than returning a guessed verdict."
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
