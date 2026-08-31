"""Bounded probabilistic verification — EXACT reachability probability over the reachable graph.

``sim`` runs seeded Monte-Carlo (sampling, not verification). This asks the exact quantitative question a
stochastic system needs: what is the probability of eventually reaching a target set? Actions carry a
relative WEIGHT per state; the enabled actions' weights form a probability distribution over successors,
turning the reachable graph into a discrete-time Markov chain (DTMC). ``reach_probability`` returns the
exact answer as a ``fractions.Fraction`` — solved by Gaussian elimination over the rationals, so there is
no floating-point error and NO dependency (numpy is only ever an optional accelerator for large systems).

The standard three-way split (Baier & Katoen, *Principles of Model Checking*, ch. 10): target states have
probability 1; states that cannot reach the target have probability 0; the rest solve the linear system
``x_s = sum_s' P(s, s') x_s'``.

``reach_probability_mdp`` adds NONDETERMINISTIC choice on top of the DTMC: a caller-supplied ``moves``
function partitions each state's enabled actions into the moves a scheduler may pick between, and the
actions WITHIN a move form the probability distribution (via ``weight``). This is a Markov decision
process (MDP); ``optimize="max"`` / ``"min"`` returns the maximal / minimal reachability probability over
all schedulers, solved EXACTLY by policy iteration (each policy's value is an exact DTMC solve; the policy
is improved until stable). Both functions take an optional ``steps=k`` for the exact probability of
reaching the target WITHIN ``k`` transitions (a finite unrolling, no fixed point). ``expected_reward``
answers the dual quantitative question: the exact expected accumulated cost (default: number of steps) to
reach the target in a DTMC, finite only when the target is reached almost surely. ``long_run_probability``
answers the steady-state question: the exact fraction of time the DTMC spends in a target set in the limit,
by decomposing into bottom SCCs and solving each one's stationary distribution exactly; ``long_run_reward``
generalises it to the steady-state average of any per-state reward (a net rate, which may be negative).
``probability_ltl``
answers the exact probability that a random DTMC run satisfies an LTL formula, for the reducible F / G / GF /
FG fragment. See PROBABILISTIC_NOTES.md.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from fractions import Fraction
from itertools import product
from typing import Literal

from musil.core import Action, Graph, Model, actions_source, explore
from musil.liveness import tarjan

# intra-package reuse of the LTL normaliser + state-predicate compiler for the reducible PLTL fragment
from musil.ltl import (
    LTL,
    Always,
    Eventually,
    _push_negations,  # pyright: ignore[reportPrivateUsage]
    _state_predicate,  # pyright: ignore[reportPrivateUsage]
)

# A distribution over successors: (probability, successor) pairs summing to 1 (empty = absorbing / no move).
type _Dist[S] = list[tuple[Fraction, S]]

# A moves function: given a state and its enabled actions, return the moves a scheduler picks between. Each
# move is a group of actions whose weights form one probability distribution over successors. A singleton
# group is a Dirac move; grouping every enabled action into one move recovers the DTMC (no nondeterminism).
type Moves[S] = Callable[[S, tuple[Action[S], ...]], Iterable[Sequence[Action[S]]]]


def _uniform(_name: str, _s: object) -> int:
    return 1


def _weight_of[S](weight: Callable[[str, S], Fraction | int], name: str, state: S) -> Fraction:
    """One action's weight as a NON-NEGATIVE ``Fraction``. Weights are relative likelihoods that normalise
    into a probability distribution over successors, so a negative weight is never meaningful — it would
    otherwise silently produce a bogus 'probability' (negative, or >1, or a spurious 0 when the weights sum to
    zero). Raising here turns that into a clear error rather than a wrong quantitative answer."""
    wt = Fraction(weight(name, state))
    if wt < 0:
        raise ValueError(f"probabilistic weight must be non-negative, but weight({name!r}, ...) = {wt}")
    return wt


def _solve_linear(matrix: list[list[Fraction]], rhs: list[Fraction]) -> list[Fraction]:
    """Solve ``matrix @ x = rhs`` exactly by Gauss-Jordan elimination over the rationals. ``matrix`` is
    square and non-singular here (it is ``I - P`` restricted to the states that can, but have not yet,
    reached the target, which is always invertible)."""
    n = len(rhs)
    aug = [[*matrix[i], rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if aug[r][col] != 0), None)
        if pivot is None:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        p = aug[col][col]
        aug[col] = [x / p for x in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col]
                aug[r] = [row - factor * piv for piv, row in zip(aug[col], aug[r], strict=True)]
    return [aug[i][n] for i in range(n)]


def _dtmc_values[S: Hashable](
    states: Sequence[S],
    dist: Mapping[S, _Dist[S]],
    target: Callable[[S], bool],
) -> dict[S, Fraction]:
    """Exact reachability probability of EVERY state of a DTMC given each state's successor distribution.

    ``dist[s]`` is the (probability, successor) distribution out of ``s`` (empty = absorbing). Applies the
    three-way split: target -> 1; states from which the target is unreachable under this distribution -> 0
    (found by backward reachability over the support); the rest solve ``(I - P) x = b`` exactly."""
    pred: dict[S, list[S]] = {s: [] for s in states}
    for s in states:
        for _, t in dist[s]:
            pred[t].append(s)
    can_reach: set[S] = {s for s in states if target(s)}
    frontier = list(can_reach)
    while frontier:
        s = frontier.pop()
        for p in pred[s]:
            if p not in can_reach:
                can_reach.add(p)
                frontier.append(p)
    unknown = [s for s in states if not target(s) and s in can_reach]
    index = {s: i for i, s in enumerate(unknown)}
    n = len(unknown)
    a = [[Fraction(0) for _ in range(n)] for _ in range(n)]
    b = [Fraction(0) for _ in range(n)]
    for s in unknown:
        i = index[s]
        a[i][i] = Fraction(1)
        for p, t in dist[s]:
            if target(t):
                b[i] += p
            elif t in index:
                a[i][index[t]] -= p
            # else t cannot reach the target -> contributes 0
    solution = _solve_linear(a, b)
    out: dict[S, Fraction] = {}
    for s in states:
        if target(s):
            out[s] = Fraction(1)
        elif s in index:
            out[s] = solution[index[s]]
        else:
            out[s] = Fraction(0)
    return out


def _normalize[S: Hashable](
    contributions: Iterable[tuple[str, S]], state: S, weight: Callable[[str, S], Fraction | int]
) -> _Dist[S]:
    """Turn ``(action_name, successor)`` contributions at ``state`` into a normalized distribution, summing
    the weight of edges that land on the same successor. Zero total weight -> empty (absorbing)."""
    pairs = [(_weight_of(weight, name, state), nxt) for name, nxt in contributions]
    total = sum((wt for wt, _ in pairs), Fraction(0))
    if total == 0:
        return []
    acc: dict[S, Fraction] = {}
    for wt, nxt in pairs:
        acc[nxt] = acc.get(nxt, Fraction(0)) + wt / total
    return [(p, t) for t, p in acc.items()]


def _immediate_cost[S: Hashable](
    edges: Iterable[tuple[str, S]],
    state: S,
    weight: Callable[[str, S], Fraction | int],
    cost: Callable[[str, S], Fraction | int],
) -> Fraction:
    """The expected COST of one step out of ``state``: each enabled action's ``cost`` weighted by its
    normalized probability. Zero when the state has no outgoing edge (absorbing)."""
    pairs = [(_weight_of(weight, name, state), name) for name, _ in edges]
    total = sum((wt for wt, _ in pairs), Fraction(0))
    if total == 0:
        return Fraction(0)
    return sum((wt / total * Fraction(cost(name, state)) for wt, name in pairs), Fraction(0))


def _mdp_moves[S: Hashable](
    model: Model[S], graph: Graph[S], moves: Moves[S], weight: Callable[[str, S], Fraction | int]
) -> dict[S, list[_Dist[S]]]:
    """Per state, the scheduler's moves as normalized distributions over successors, from the canonical edges
    ``explore`` already computed (group each move's actions by name, so no canonicalization is redone). A state
    with no move gets a single absorbing (empty) move. Shared by ``reach_probability_mdp`` and the MDP path of
    ``probability_ltl`` so they cannot drift in how the MDP is built."""
    source = actions_source(model)
    all_moves: dict[S, list[_Dist[S]]] = {}
    for s in graph.states:
        by_name = {name: nxt for name, nxt in graph.edges.get(s, ())}
        enabled = tuple(a for a in source(s) if a.enabled(s))
        state_moves = [
            _normalize([(a.name, by_name[a.name]) for a in group if a.name in by_name], s, weight)
            for group in moves(s, enabled)
        ]
        all_moves[s] = state_moves if state_moves else [[]]  # no move -> a single absorbing move
    return all_moves


def reach_probability[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    avoid: Callable[[S], bool] | None = None,
    steps: int | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact probability of eventually reaching a ``target`` state from the model's initial state,
    treating the reachable graph as a DTMC.

    At each state the enabled actions' ``weight(action_name, state)`` values are normalised into a
    probability distribution over the successors (edges to the same successor sum); the default weight is
    ``1`` for every action, i.e. a uniform choice. A weight must be NON-NEGATIVE — a negative one raises
    ``ValueError`` rather than silently producing a bogus probability (this holds for every function here that
    takes a ``weight``). States must be HASHABLE (the graph is explored). Returns a ``fractions.Fraction`` —
    exact, no floating point.

    ``avoid`` gives the CONSTRAINED (until) probability ``P(¬avoid U target)``: the probability of reaching
    ``target`` WITHOUT first entering an ``avoid`` state. An ``avoid`` state that is not itself a ``target``
    becomes an absorbing failure (probability 0), so a run that touches it before the target does not count;
    ``target`` takes precedence (a state in both counts as reached). With no ``avoid`` (the default) it is
    plain reachability.

    With ``steps=k`` the answer is the probability of reaching ``target`` WITHIN ``k`` transitions (an exact
    finite unrolling; ``steps=0`` is the indicator of ``target``). With ``steps=None`` (the default) it is
    the unbounded probability, solved by the exact linear system. Raises ``ValueError`` if the exploration
    truncates at ``max_states`` (the probability would be inconclusive) or if ``steps`` is negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("reach_probability: exploration truncated at max_states; the probability is inconclusive")
    w = weight if weight is not None else _uniform
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    if avoid is not None:  # ¬avoid U target: avoid (non-target) states are absorbing 0-sinks
        dist = {s: ([] if (avoid(s) and not target(s)) else d) for s, d in dist.items()}
    if steps is None:
        return _dtmc_values(graph.states, dist, target)[graph.initial[0]]
    if steps < 0:
        raise ValueError(f"reach_probability: steps must be non-negative, got {steps}")
    return _bounded_values(graph.states, {s: [dist[s]] for s in graph.states}, target, steps, minimize=False)[
        graph.initial[0]
    ]


def transient_distribution[S: Hashable](
    model: Model[S],
    steps: int,
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    max_states: int = 1_000_000,
) -> dict[S, Fraction]:
    """The exact probability distribution over states AFTER EXACTLY ``steps`` transitions of the DTMC, from the
    initial state — ``dict[state, Fraction]`` summing to 1 (PRISM's transient / instantaneous analysis). A
    forward push: ``pi_0`` puts all mass on the initial state (the first, if several); ``pi_{i+1}(s') = sum_s
    pi_i(s) P(s, s')``. Exact, no fixed point — ``steps=0`` is the point mass on the initial state.

    An absorbing / deadlock state (no outgoing edge) keeps its mass, so a run that has stopped there stays
    counted. Point-in-time queries follow: ``sum(pi[s] for s in states if target(s))`` is the probability of
    being in the target set AT step ``k`` — distinct from ``reach_probability(steps=k)``, which is the
    probability of reaching it WITHIN ``k``. Raises ``ValueError`` if the exploration truncates or ``steps`` is
    negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("transient_distribution: exploration truncated at max_states; the answer is inconclusive")
    if steps < 0:
        raise ValueError(f"transient_distribution: steps must be non-negative, got {steps}")
    w = weight if weight is not None else _uniform
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    pi = dict.fromkeys(graph.states, Fraction(0))
    pi[graph.initial[0]] = Fraction(1)
    for _ in range(steps):
        nxt = dict.fromkeys(graph.states, Fraction(0))
        for s, mass in pi.items():
            if mass == 0:
                continue
            successors = dist[s]
            if not successors:  # absorbing / deadlock: the mass stays put
                nxt[s] += mass
            else:
                for p, t in successors:
                    nxt[t] += mass * p
        pi = nxt
    return pi


def expected_reward[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    cost: Callable[[str, S], Fraction | int] | None = None,
    steps: int | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact EXPECTED accumulated cost to first reach ``target`` from the model's initial state,
    treating the reachable graph as a DTMC. With the default unit ``cost`` this is the expected number of
    STEPS to reach the target.

    ``weight`` normalises the enabled actions into a distribution over successors exactly as in
    ``reach_probability``; ``cost(action_name, state)`` is the cost charged for firing that action (default
    ``1``). Returns a ``fractions.Fraction`` — exact, no floating point, solving ``E(s) = 0`` on the target
    and ``E(s) = sum_s' P(s, s') (cost + E(s'))`` elsewhere.

    With ``steps=k`` the answer is instead the expected cost accumulated until the target is reached OR ``k``
    steps elapse, whichever comes first — a finite backward induction (``E_0 = 0``; ``E_i(s) = cost(s) + sum_s'
    P(s,s') E_{i-1}(s')`` off the target). Always finite, so it needs no almost-sure-reachability guard; a
    bounded horizon is the natural "expected cost in the next ``k`` steps" question. With ``steps=None`` (the
    default) it is the unbounded expected cost to reach the target, which is finite only if the target is
    reached ALMOST SURELY; otherwise it is infinite, so this raises ``ValueError`` when ``reach_probability``
    from the initial state is not exactly 1. Also raises ``ValueError`` if the exploration truncates at
    ``max_states`` or if ``steps`` is negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("expected_reward: exploration truncated at max_states; the expectation is inconclusive")
    init = graph.initial[0]
    if target(init):
        return Fraction(0)
    w = weight if weight is not None else _uniform
    c = cost if cost is not None else _uniform  # default cost 1 per step -> expected number of steps
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    if steps is not None:  # bounded horizon: a finite induction, always finite (no a.s. guard needed)
        if steps < 0:
            raise ValueError(f"expected_reward: steps must be non-negative, got {steps}")
        ic = {s: _immediate_cost(graph.edges.get(s, ()), s, w, c) for s in graph.states}
        values = dict.fromkeys(graph.states, Fraction(0))
        for _ in range(steps):
            values = {
                s: (Fraction(0) if target(s) else ic[s] + _move_value(dist[s], values)) for s in graph.states
            }
        return values[init]
    if _dtmc_values(graph.states, dist, target)[init] != 1:
        raise ValueError(
            "expected_reward: the target is not reached almost surely from the initial state "
            "(reach probability < 1), so the expected cost is infinite"
        )
    # Every explored state is reachable from init, and init reaches the target a.s., so every non-target
    # state also reaches it a.s. (a transient state that failed with positive probability would drag init's
    # reach probability below 1). Hence (I - P) restricted to the non-target states is non-singular.
    unknown = [s for s in graph.states if not target(s)]
    index = {s: i for i, s in enumerate(unknown)}
    n = len(unknown)
    a = [[Fraction(0) for _ in range(n)] for _ in range(n)]
    b = [Fraction(0) for _ in range(n)]
    for s in unknown:
        i = index[s]
        a[i][i] = Fraction(1)
        edges = graph.edges.get(s, ())
        total = sum((_weight_of(w, name, s) for name, _ in edges), Fraction(0))
        for name, nxt in edges:
            p = _weight_of(w, name, s) / total
            b[i] += p * Fraction(c(name, s))  # expected immediate cost of this transition
            if not target(nxt):
                a[i][index[nxt]] -= p
    return _solve_linear(a, b)[index[init]]


def _move_value[S: Hashable](move: _Dist[S], values: Mapping[S, Fraction]) -> Fraction:
    """Expected value of a move: sum over its (probability, successor) pairs of ``p * values[successor]``."""
    return sum((p * values[t] for p, t in move), Fraction(0))


def _bounded_values[S: Hashable](
    states: Sequence[S],
    all_moves: Mapping[S, list[_Dist[S]]],
    target: Callable[[S], bool],
    steps: int,
    minimize: bool,
) -> dict[S, Fraction]:
    """Exact probability of reaching ``target`` WITHIN ``steps`` transitions (optimising over the moves each
    step, ``min`` or ``max``). A finite backward induction — no fixed point, so it is exact by construction:
    ``V_0`` is the indicator of ``target``, and ``V_i(s) = opt_move sum P(s') V_{i-1}(s')`` for non-target
    ``s``. A DTMC is the single-move case (the optimisation is over one value). ``steps=0`` gives the
    indicator of ``target``."""
    values = {s: Fraction(target(s)) for s in states}
    reduce = min if minimize else max
    for _ in range(steps):
        values = {
            s: Fraction(1)
            if target(s)
            else reduce((_move_value(m, values) for m in all_moves[s]), default=Fraction(0))
            for s in states
        }
    return values


def _stationary[S: Hashable](bscc: Sequence[S], dist: Mapping[S, _Dist[S]]) -> dict[S, Fraction]:
    """The unique stationary distribution of a bottom SCC — a finite irreducible DTMC — exact over the
    rationals: the ``pi`` solving ``pi P = pi`` with ``sum pi = 1``. Set up as ``m`` equations — ``m - 1``
    balance equations ``sum_s pi(s) (P(s, t) - [s == t]) = 0`` plus the normalization ``sum pi = 1`` replacing
    the last (redundant) balance row — and solved by the shared Gauss-Jordan. A singleton BSCC (a self-loop
    state, or an absorbing / deadlock state) reduces to the normalization alone, giving ``pi = 1`` there.
    Being the stationary distribution, it is also the long-run fraction of time spent in each state, EQUAL to
    the time average even for a periodic BSCC (where ``P^n`` does not converge but the Cesàro average does)."""
    m = len(bscc)
    idx = {s: i for i, s in enumerate(bscc)}
    a = [[Fraction(0) for _ in range(m)] for _ in range(m)]
    b = [Fraction(0) for _ in range(m)]
    for i, t in enumerate(bscc):
        if i < m - 1:  # balance row for t: sum_j pi_j * (P(s_j, t) - [s_j == t]) = 0
            a[i][i] -= Fraction(1)  # the -[s == t] diagonal term
            for j, s in enumerate(bscc):
                for p, succ in dist[s]:
                    if succ == t:
                        a[i][j] += p
        else:  # last row: normalization sum pi = 1 (replaces the redundant final balance equation)
            for j in range(m):
                a[i][j] = Fraction(1)
            b[i] = Fraction(1)
    solution = _solve_linear(a, b)
    return {s: solution[idx[s]] for s in bscc}


def long_run_reward[S: Hashable](
    model: Model[S],
    reward: Callable[[S], Fraction | int],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact long-run AVERAGE reward per step of the DTMC (PRISM's steady-state reward ``R=? [S]``): in the
    limit, the mean of ``reward(state)`` over the run, as a ``Fraction``.

    The reachable graph is a DTMC (``weight`` normalises each state's enabled actions into a distribution, as
    in ``reach_probability``). A finite DTMC is absorbed almost surely into a BOTTOM SCC; inside each BSCC the
    long-run fraction of time in a state is its stationary probability ``pi_B(s)``, so the long-run average
    reward is, over the BSCCs ``B``, ``sum_B reach(B) * sum_{s in B} pi_B(s) * reward(s)`` — the reach-weighted
    then stationary-weighted mean of the reward. ``reward`` MAY be negative (a net cost rate); it is not a
    probability. Reachability to each BSCC reuses the exact DTMC solve, ``pi_B`` the exact stationary solve.
    ``long_run_probability(model, target)`` is the special case ``reward = 1_target`` (the target's indicator).

    Raises ``ValueError`` if the exploration truncates at ``max_states`` (the answer would be inconclusive).
    Requires hashable states (the graph is explored)."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("long_run_reward: exploration truncated at max_states; the long-run answer is inconclusive")
    w = weight if weight is not None else _uniform
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    return _long_run_reward_of(graph.states, dist, graph.initial[0], reward)


def _long_run_reward_of[S: Hashable](
    states: Sequence[S], dist: Mapping[S, _Dist[S]], init: S, reward: Callable[[S], Fraction | int]
) -> Fraction:
    """The long-run average reward of a DTMC given directly as its per-state distribution ``dist``:
    ``sum_B reach(B) * sum_{s in B} pi_B(s) * reward(s)`` over the bottom SCCs. Shared by ``long_run_reward``
    (the model builds ``dist``) and ``long_run_reward_mdp`` (each policy induces a ``dist``)."""
    support: dict[S, list[tuple[str, S]]] = {s: [("", t) for _, t in dist[s]] for s in states}
    total = Fraction(0)
    for scc in tarjan(set(states), support):
        if any(t not in scc for s in scc for _, t in dist[s]):
            continue  # not a BOTTOM SCC: a distribution edge leaves it, so the run does not stay here
        pi = _stationary(list(scc), dist)
        avg = sum((pi[s] * Fraction(reward(s)) for s in scc), Fraction(0))  # stationary-weighted reward in B
        if avg == 0:
            continue  # this BSCC contributes no long-run reward
        reach_b = _dtmc_values(states, dist, scc.__contains__)[init]
        total += reach_b * avg
    return total


def long_run_probability[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact long-run (steady-state) fraction of time the DTMC spends in ``target`` states, from the
    initial state — the answer to "in the limit, what proportion of the time is the system in a target
    state?" (PRISM's steady-state / S operator). A ``Fraction``, no floating point.

    The reachable graph is a DTMC (each state's enabled actions' ``weight`` normalise into a distribution
    over successors, as in ``reach_probability``). A finite DTMC is absorbed almost surely into one of its
    BOTTOM strongly-connected components (BSCCs); inside each BSCC — a finite irreducible chain — the long-run
    fraction of time in each state is its stationary probability. So the answer is, over the BSCCs ``B``, the
    sum of ``P(the run is absorbed into B)`` times ``B``'s stationary mass on the target states:
    ``sum_B reach(B) * sum_{s in B, target(s)} pi_B(s)``. Reachability to each BSCC reuses the exact DTMC
    solve; ``pi_B`` is the exact stationary solve (``_stationary``). Transient states carry zero long-run
    measure. An absorbing / deadlock state is treated as self-absorbing (it forms its own BSCC with mass 1).

    Raises ``ValueError`` if the exploration truncates at ``max_states`` (the answer would be inconclusive).
    Requires hashable states (the graph is explored). Equals ``long_run_reward`` with the target's indicator
    as the reward (this delegates to it)."""
    return long_run_reward(model, lambda s: Fraction(target(s)), weight=weight, max_states=max_states)


def long_run_reward_mdp[S: Hashable](
    model: Model[S],
    reward: Callable[[S], Fraction | int],
    *,
    moves: Moves[S],
    weight: Callable[[str, S], Fraction | int] | None = None,
    optimize: Literal["max", "min"] = "max",
    max_policies: int = 100_000,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact MAXIMAL (or MINIMAL) long-run average reward over all schedulers of the MDP — the steady-state
    reward RATE a best/worst scheduler achieves. ``moves``/``weight`` describe the MDP as in
    ``reach_probability_mdp``; ``reward(state)`` is the per-state rate (may be negative).

    This is the pure-Python REFERENCE ORACLE: a finite MDP has an average-optimal MEMORYLESS DETERMINISTIC
    policy (Puterman), so the optimum over ALL schedulers equals the best/worst over the finitely many
    memoryless deterministic policies — enumerate them, induce each one's DTMC, and take the extreme of
    ``long_run_reward``. Exact and dependency-free. It is EXPONENTIAL in the number of states with a genuine
    choice (the product of their move-counts), so it is for SMALL MDPs; ``max_policies`` caps that product and
    raises a loud ``ValueError`` past it rather than hanging. An efficient average-reward policy iteration is
    the future accelerator (see PROBABILISTIC_NOTES.md), to be differential-tested against this oracle.

    Raises ``ValueError`` if the exploration truncates, if the policy count exceeds ``max_policies``, or if
    ``optimize`` is not ``"max"``/``"min"``. Requires hashable states."""
    if optimize not in ("max", "min"):
        raise ValueError(f"long_run_reward_mdp: optimize must be 'max' or 'min', got {optimize!r}")
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("long_run_reward_mdp: exploration truncated at max_states; the answer is inconclusive")
    w = weight if weight is not None else _uniform
    all_moves = _mdp_moves(model, graph, moves, w)
    state_list = list(graph.states)
    count = 1
    for s in state_list:
        count *= len(all_moves[s])
        if count > max_policies:
            raise ValueError(
                f"long_run_reward_mdp: more than max_policies={max_policies} memoryless deterministic policies "
                "to enumerate (the product of the states' move-counts); this reference oracle is for small "
                "MDPs. Raise max_policies deliberately, or wait for the policy-iteration accelerator."
            )
    init = graph.initial[0]
    pick = max if optimize == "max" else min
    best: Fraction | None = None
    for combo in product(*(range(len(all_moves[s])) for s in state_list)):
        induced = {s: all_moves[s][combo[i]] for i, s in enumerate(state_list)}  # this policy's DTMC
        value = _long_run_reward_of(state_list, induced, init, reward)
        best = value if best is None else pick(best, value)
    assert best is not None  # at least one policy exists (each state has >= 1 move)
    return best


def _bscc_reach_sum[S: Hashable](
    states: Sequence[S], dist: Mapping[S, _Dist[S]], init: S, keep: Callable[[frozenset[S]], bool]
) -> Fraction:
    """Sum of ``P(the run is absorbed into B)`` over the bottom SCCs ``B`` that satisfy ``keep`` — the exact
    probability that the DTMC ends up cycling forever in one of the kept BSCCs. Used for the repeated- and
    persistent-reachability probabilities (GF / FG of a state predicate)."""
    support: dict[S, list[tuple[str, S]]] = {s: [("", t) for _, t in dist[s]] for s in states}
    total = Fraction(0)
    for scc in tarjan(set(states), support):
        if any(t not in scc for s in scc for _, t in dist[s]):
            continue  # not a bottom SCC
        b = frozenset(scc)
        if keep(b):
            total += _dtmc_values(states, dist, b.__contains__)[init]
    return total


def _maximal_end_components[S: Hashable](
    states: Sequence[S], all_moves: Mapping[S, list[_Dist[S]]]
) -> list[frozenset[S]]:
    """The maximal end components of the MDP: maximal sets ``C`` of states in which the scheduler can choose,
    per state, a move whose whole probability mass stays inside ``C`` and makes the sub-MDP strongly connected
    — the sets it can stay inside forever and cycle within. Computed by the standard refinement (Baier &
    Katoen / de Alfaro): SCC-decompose using only moves that stay inside the current candidate, drop any state
    with no staying move, and reprocess the remainder until stable. An absorbing state (empty move) stays
    trivially, so it is its own singleton MEC — consistent with the DTMC treatment of a deadlock as absorbing.
    Used for the MDP repeated-reachability (GF) probability."""
    result: list[frozenset[S]] = []
    stack: list[set[S]] = [set(states)]
    while stack:
        t = stack.pop()
        # successor graph within t, via NON-EMPTY moves whose whole support stays in t
        succ: dict[S, list[tuple[str, S]]] = {s: [] for s in t}
        for s in t:
            for move in all_moves[s]:
                post = {nxt for _, nxt in move}
                if post and post <= t:
                    succ[s].extend(("", nxt) for nxt in post)
        for scc in tarjan(set(t), succ):
            # a state "stays" in scc if some move's support is inside scc (the empty/absorbing move stays)
            remove = {s for s in scc if not any({nxt for _, nxt in move} <= scc for move in all_moves[s])}
            if not remove:
                result.append(frozenset(scc))
            elif scc - remove:
                stack.append(scc - remove)
    return result


def _stay_within[S: Hashable](
    states: Sequence[S], all_moves: Mapping[S, list[_Dist[S]]], keep: Callable[[S], bool]
) -> set[S]:
    """The greatest set ``U`` of ``keep`` states in which the scheduler can stay FOREVER: every state in ``U``
    has a move whose whole support lies in ``U`` (an absorbing/empty move stays trivially). Computed by
    iterative removal. This is the target region for PERSISTENT reachability (``FG keep``): once in ``U`` the
    scheduler can keep the run inside ``keep`` for good, so ``P_max(FG keep) = P_max(reach U))``."""
    u = {s for s in states if keep(s)}
    changed = True
    while changed:
        changed = False
        for s in list(u):
            if not any({t for _, t in move} <= u for move in all_moves[s]):
                u.discard(s)
                changed = True
    return u


def _negate[S: Hashable](pred: Callable[[S], bool]) -> Callable[[S], bool]:
    """The pointwise negation of a state predicate (for the min-direction duals: ``¬GF p = FG ¬p``)."""
    return lambda s: not pred(s)


def probability_ltl[S: Hashable](
    model: Model[S],
    formula: LTL[S],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    moves: Moves[S] | None = None,
    optimize: Literal["max", "min"] = "max",
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact probability that a run satisfies the LTL ``formula`` (PRISM's P operator), a ``Fraction``.

    With no ``moves`` (the default) the reachable graph is a DTMC (``weight`` normalises each state's enabled
    actions into a distribution; a negative weight raises), and the answer is the probability a RANDOM run
    satisfies ``formula``, for the fragment with a direct characterisation — a temporal operator on a STATE
    predicate ``p``:

    - ``F p`` → the reachability probability of ``p``;
    - ``G p`` → ``1 - P(F ¬p)``;
    - ``GF p`` (``Always(Eventually p)``) → the probability of absorption into a bottom SCC that CONTAINS a
      ``p`` state (a run visits every state of its absorbing BSCC infinitely often);
    - ``FG p`` (``Eventually(Always p)``) → the probability of absorption into a bottom SCC ENTIRELY inside
      ``p``.

    With ``moves`` (as in ``reach_probability_mdp``) the model is an MDP and the answer is the OPTIMAL
    probability over all schedulers, ``optimize="max"`` or ``"min"``, for the same F / G / GF / FG fragment:

    - ``F p`` → max / min reachability of ``p``;
    - ``G p`` → ``1 - P_min(F ¬p)`` (max) / ``1 - P_max(F ¬p)`` (min);
    - ``GF p`` (Büchi) → the max probability equals the max reachability to the states in a MAXIMAL END
      COMPONENT that contains a ``p`` state (reach such a component and cycle through ``p`` forever); the min is
      the dual ``1 - P_max(FG ¬p)``;
    - ``FG p`` (co-Büchi) → the max probability equals the max reachability to the region the scheduler can
      stay inside ``p`` forever (``_stay_within``); the min is the dual ``1 - P_max(GF ¬p)``.

    All exact, reusing the reachability solve, the BSCC / MEC / stay-within decompositions and (for the MDP)
    policy iteration; NO linear programming (that is only for the long-run AVERAGE reward, see
    PROBABILISTIC_NOTES.md). Any formula outside this fragment raises ``NotImplementedError`` — general
    probabilistic LTL needs a DETERMINISTIC automaton for the formula (a Safra/Rabin construction), not yet
    built. Raises ``ValueError`` if the exploration truncates."""
    phi = _push_negations(formula)
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("probability_ltl: exploration truncated at max_states; the probability is inconclusive")
    w = weight if weight is not None else _uniform
    init = graph.initial[0]

    if moves is not None:  # MDP path: the optimal probability over schedulers
        all_moves = _mdp_moves(model, graph, moves, w)
        states = graph.states

        def reach_max(pred: Callable[[S], bool]) -> Fraction:
            return _reach_policy_iteration(states, all_moves, pred, minimize=False, absorbing=set[S]())[0][init]

        def reach_min(pred: Callable[[S], bool]) -> Fraction:
            absorbing = _s0_min(states, all_moves, pred)  # states that can avoid pred forever -> pinned to 0
            return _reach_policy_iteration(states, all_moves, pred, minimize=True, absorbing=absorbing)[0][init]

        def gf_max(pred: Callable[[S], bool]) -> Fraction:  # reach a MEC that contains a pred state, then cycle
            good = {s for c in _maximal_end_components(states, all_moves) if any(pred(x) for x in c) for s in c}
            return reach_max(good.__contains__)

        def fg_max(pred: Callable[[S], bool]) -> Fraction:  # reach the region the scheduler can stay in forever
            return reach_max(_stay_within(states, all_moves, pred).__contains__)

        # The whole reducible fragment for MDPs, max and min. Min follows by duality (¬GF p = FG ¬p, etc.);
        # G/F reachability duals reuse the min/max reachability directly.
        mx = optimize == "max"
        match phi:
            case Always(arg=Eventually(arg=inner)):  # GF p
                p = _state_predicate(inner)
                if p is not None:
                    return gf_max(p) if mx else 1 - fg_max(_negate(p))
            case Eventually(arg=Always(arg=inner)):  # FG p
                p = _state_predicate(inner)
                if p is not None:
                    return fg_max(p) if mx else 1 - gf_max(_negate(p))
            case Eventually(arg=inner):  # F p
                p = _state_predicate(inner)
                if p is not None:
                    return reach_max(p) if mx else reach_min(p)
            case Always(arg=inner):  # G p = 1 - P(F ¬p)
                p = _state_predicate(inner)
                if p is not None:
                    return (1 - reach_min(_negate(p))) if mx else (1 - reach_max(_negate(p)))
            case _:
                pass
        raise NotImplementedError(
            f"probability_ltl over an MDP supports F/G/GF/FG of a state predicate (max and min); {formula} "
            "needs the general probabilistic LTL engine (a deterministic automaton), not yet built"
        )

    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    match phi:
        case Always(arg=Eventually(arg=inner)):  # GF p
            p = _state_predicate(inner)
            if p is not None:
                return _bscc_reach_sum(graph.states, dist, init, lambda b: any(p(s) for s in b))
        case Eventually(arg=Always(arg=inner)):  # FG p
            p = _state_predicate(inner)
            if p is not None:
                return _bscc_reach_sum(graph.states, dist, init, lambda b: all(p(s) for s in b))
        case Eventually(arg=inner):  # F p
            p = _state_predicate(inner)
            if p is not None:
                return _dtmc_values(graph.states, dist, p)[init]
        case Always(arg=inner):  # G p = 1 - P(F !p)
            p = _state_predicate(inner)
            if p is not None:
                return 1 - _dtmc_values(graph.states, dist, lambda s, _p=p: not _p(s))[init]
        case _:
            pass
    raise NotImplementedError(
        f"probability_ltl supports F/G/GF/FG of a state predicate; {formula} needs the general probabilistic "
        "LTL engine (a deterministic automaton for the formula), which is not yet built"
    )


def _s0_min[S: Hashable](
    states: Sequence[S], all_moves: Mapping[S, list[_Dist[S]]], target: Callable[[S], bool]
) -> set[S]:
    """The states with MINIMAL reachability probability 0 — those from which a scheduler can avoid the
    target forever. This is the greatest ``U`` (subset of the non-target states) such that every state in
    ``U`` has some move whose support stays inside ``U`` (including an absorbing/empty move, which trivially
    stays). Computed by iterative removal: drop any state with no staying move, until a fixed point.

    This is the precomputation min-reachability needs and max does not: without it, policy iteration for min
    stalls on a self-loop move whose value equals the current (wrong) value, never reaching the true 0."""
    u = {s for s in states if not target(s)}
    changed = True
    while changed:
        changed = False
        for s in list(u):
            if not any(all(t in u for _, t in move) for move in all_moves[s]):
                u.discard(s)
                changed = True
    return u


def _reach_policy_iteration[S: Hashable](
    states: Sequence[S],
    all_moves: Mapping[S, list[_Dist[S]]],
    target: Callable[[S], bool],
    *,
    minimize: bool,
    absorbing: set[S],
) -> tuple[dict[S, Fraction], dict[S, int]]:
    """Optimal (max or min) reachability probability of every state AND the optimal memoryless policy, by
    policy iteration. Each improvement switches a state only to a STRICTLY better move under the current
    exact values, so the values move monotonically and no policy repeats -> it terminates (finite policy
    space). ``absorbing`` states are pinned to 0 (used for the min ``_s0_min`` set)."""
    policy: dict[S, int] = dict.fromkeys(states, 0)
    while True:
        dist = {s: ([] if s in absorbing else all_moves[s][policy[s]]) for s in states}
        values = _dtmc_values(states, dist, target)
        changed = False
        for s in states:
            if target(s) or s in absorbing:
                continue
            best_i, best_v = policy[s], _move_value(all_moves[s][policy[s]], values)
            for i, move in enumerate(all_moves[s]):
                v = _move_value(move, values)
                if (v < best_v) if minimize else (v > best_v):
                    best_i, best_v = i, v
            if best_i != policy[s]:
                policy[s] = best_i
                changed = True
        if not changed:
            return values, policy


def reach_probability_mdp[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    moves: Moves[S],
    weight: Callable[[str, S], Fraction | int] | None = None,
    optimize: Literal["max", "min"] = "max",
    avoid: Callable[[S], bool] | None = None,
    steps: int | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact MAXIMAL (or MINIMAL) probability of eventually reaching ``target`` over all schedulers of
    the MDP.

    ``moves(state, enabled_actions)`` partitions the enabled actions into the moves a scheduler chooses
    between at ``state``; the actions within a move form one distribution over successors (their ``weight``
    normalised, default uniform). Grouping every enabled action into a single move recovers
    ``reach_probability`` (a DTMC has no choice).

    Solved EXACTLY by policy iteration: evaluate the current policy as a DTMC (an exact rational solve),
    then switch each state to a strictly better move under those values, until the policy is stable — a
    ``fractions.Fraction``. For ``optimize="min"`` the states from which a scheduler can avoid the target
    forever are found first (``_s0_min``) and pinned to 0, which is what stops min policy iteration from
    stalling on a value-preserving self-loop (see PROBABILISTIC_NOTES.md).

    ``avoid`` gives the CONSTRAINED (until) optimal probability ``P_opt(¬avoid U target)``: an ``avoid`` state
    that is not a ``target`` becomes an absorbing failure (0), so a run that touches it before the target does
    not count. The optimisation is still over all schedulers — e.g. ``optimize="max"`` is the best a scheduler
    can do while steering clear of ``avoid`` until the target.

    With ``steps=k`` the answer is instead the optimal probability of reaching ``target`` WITHIN ``k``
    transitions — an exact finite backward induction, so ``_s0_min`` is not needed (a bounded horizon cannot
    stall). Raises ``ValueError`` if the exploration truncates at ``max_states`` or if ``steps`` is
    negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("reach_probability_mdp: exploration truncated at max_states; the probability is inconclusive")
    w = weight if weight is not None else _uniform
    all_moves = _mdp_moves(model, graph, moves, w)
    if avoid is not None:  # ¬avoid U target: avoid (non-target) states become absorbing 0-sinks
        absorbing_move: list[_Dist[S]] = [[]]
        all_moves = {s: (absorbing_move if (avoid(s) and not target(s)) else m) for s, m in all_moves.items()}
    minimize = optimize == "min"
    if steps is not None:
        if steps < 0:
            raise ValueError(f"reach_probability_mdp: steps must be non-negative, got {steps}")
        return _bounded_values(graph.states, all_moves, target, steps, minimize)[graph.initial[0]]
    # For min, pin the "can avoid the target forever" states to 0 by making them absorbing before iterating;
    # for max they need no special treatment (unreachable-to-target already resolves to 0 in _dtmc_values).
    absorbing = _s0_min(graph.states, all_moves, target) if minimize else set[S]()
    values, _ = _reach_policy_iteration(graph.states, all_moves, target, minimize=minimize, absorbing=absorbing)
    return values[graph.initial[0]]


def expected_reward_mdp[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    moves: Moves[S],
    weight: Callable[[str, S], Fraction | int] | None = None,
    cost: Callable[[str, S], Fraction | int] | None = None,
    optimize: str = "min",
    steps: int | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact MINIMAL (``optimize="min"``, default) or MAXIMAL (``optimize="max"``) expected accumulated
    cost to first reach ``target`` over all schedulers of the MDP — the stochastic shortest / longest path.

    With ``steps=k`` the answer is instead the min/max expected cost accumulated until the target is reached OR
    ``k`` steps elapse — a finite backward induction over the moves each step, always finite, so it needs no
    reachability guard (the "expected cost in the next ``k`` steps under the best/worst scheduler").
    With the default unit ``cost`` this is the min/max expected number of STEPS. ``moves``/``weight`` describe
    the MDP exactly as in ``reach_probability_mdp``; ``cost`` must be POSITIVE (the default unit cost is), so
    that a scheduler which fails to reach the target a.s. has infinite cost — the assumption both directions
    rest on. Each policy is evaluated by an exact rational solve of ``E(s) = cost(s) + sum_s' P(s,s') E(s')``.

    MIN is the stochastic shortest path. A proper policy must EXIST for the min to be finite: the
    max-reachability-optimal policy reaches the target almost surely from every state whose max reachability is
    1 (a convex combination of values ``<= 1`` equal to 1 forces every successor to 1), so it is proper there
    and seeds the iteration, which then minimises over the moves whose successors are all proper.

    MAX is the stochastic LONGEST path, finite only when EVERY policy is proper — otherwise a scheduler can
    loop away from the target forever and the max is infinite. So the guard is MIN reachability 1 from the
    initial state (no scheduler avoids the target); it implies min reachability 1 from every reachable state,
    hence every policy is proper and the max over the finite policy space is finite. Any policy is then a valid
    proper seed, and maximising policy iteration (each switch strictly RAISES a bounded, monotone value)
    converges to the optimum (Bertsekas & Tsitsiklis SSP, the all-proper case).

    Raises ``ValueError`` if the required reachability guard fails from the initial state (the expectation is
    then infinite: min — no scheduler reaches a.s.; max — some scheduler avoids the target with positive
    probability), if ``optimize`` is not ``"min"``/``"max"``, or if the exploration truncates."""
    if optimize not in ("min", "max"):
        raise ValueError(f"expected_reward_mdp: optimize must be 'min' or 'max', got {optimize!r}")
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("expected_reward_mdp: exploration truncated at max_states; the expectation is inconclusive")
    init = graph.initial[0]
    if target(init):
        return Fraction(0)
    source = actions_source(model)
    w = weight if weight is not None else _uniform
    c = cost if cost is not None else _uniform  # default cost 1 per step -> expected number of steps
    # Per state: each move's distribution AND its expected immediate cost, from the canonical edges.
    all_moves: dict[S, list[_Dist[S]]] = {}
    all_costs: dict[S, list[Fraction]] = {}
    for s in graph.states:
        by_name = {name: nxt for name, nxt in graph.edges.get(s, ())}
        enabled = tuple(a for a in source(s) if a.enabled(s))
        state_moves: list[_Dist[S]] = []
        state_costs: list[Fraction] = []
        for group in moves(s, enabled):
            members = [a for a in group if a.name in by_name]
            total = sum((_weight_of(w, a.name, s) for a in members), Fraction(0))
            acc: dict[S, Fraction] = {}
            move_cost = Fraction(0)
            if total != 0:
                for a in members:
                    p = _weight_of(w, a.name, s) / total
                    acc[by_name[a.name]] = acc.get(by_name[a.name], Fraction(0)) + p
                    move_cost += p * Fraction(c(a.name, s))
            state_moves.append([(p, t) for t, p in acc.items()])
            state_costs.append(move_cost)
        all_moves[s] = state_moves if state_moves else [[]]
        all_costs[s] = state_costs if state_costs else [Fraction(0)]
    if steps is not None:  # bounded horizon: a finite induction over moves, always finite (no guard needed)
        if steps < 0:
            raise ValueError(f"expected_reward_mdp: steps must be non-negative, got {steps}")
        pick = min if optimize == "min" else max
        values = dict.fromkeys(graph.states, Fraction(0))
        for _ in range(steps):
            values = {
                s: (
                    Fraction(0)
                    if target(s)
                    else pick(all_costs[s][j] + _move_value(all_moves[s][j], values) for j in range(len(all_moves[s])))
                )
                for s in graph.states
            }
        return values[init]
    if optimize == "min":
        # A proper policy must EXIST (max reachability 1); the max-optimal policy is a proper seed there.
        # States that cannot reach a.s. have infinite min cost.
        reach_values, reach_policy = _reach_policy_iteration(
            graph.states, all_moves, target, minimize=False, absorbing=set[S]()
        )
        if reach_values[init] != 1:
            raise ValueError(
                "expected_reward_mdp: no scheduler reaches the target almost surely from the initial state, "
                "so the minimal expected cost is infinite"
            )
        proper = {s for s in graph.states if reach_values[s] == 1}
        seed = reach_policy
    else:  # max: EVERY policy must be proper (min reachability 1), else some scheduler loops away forever.
        absorbing = _s0_min(graph.states, all_moves, target)
        reach_values, _ = _reach_policy_iteration(
            graph.states, all_moves, target, minimize=True, absorbing=absorbing
        )
        if reach_values[init] != 1:
            raise ValueError(
                "expected_reward_mdp: some scheduler avoids the target with positive probability from the "
                "initial state, so the maximal expected cost is infinite"
            )
        # min reachability 1 from init => 1 from every reachable state => every policy proper; move 0 seeds.
        proper = set(graph.states)
        seed = {s: 0 for s in graph.states}

    unknown = [s for s in proper if not target(s)]
    idx = {s: i for i, s in enumerate(unknown)}

    def _safe(move: _Dist[S]) -> bool:
        return all(t in proper for _, t in move)  # a move a proper scheduler may take (no failure branch)

    # Stochastic shortest/longest path by policy iteration, seeded proper, restricted to safe moves. Each
    # switch strictly moves a finite expected cost in the chosen direction, so it never picks an improper
    # (infinite-cost) policy and terminates at the optimum (Bertsekas & Tsitsiklis, SSP).
    minimizing = optimize == "min"
    policy = {s: seed[s] for s in unknown}
    while True:
        n = len(unknown)
        a = [[Fraction(0) for _ in range(n)] for _ in range(n)]
        b = [Fraction(0) for _ in range(n)]
        for s in unknown:
            i = idx[s]
            a[i][i] = Fraction(1)
            b[i] = all_costs[s][policy[s]]
            for p, t in all_moves[s][policy[s]]:
                if not target(t):
                    a[i][idx[t]] -= p
        solution = _solve_linear(a, b)
        e = {s: (Fraction(0) if target(s) else solution[idx[s]]) for s in proper}
        changed = False
        for s in unknown:
            best_i = policy[s]
            best_c = all_costs[s][best_i] + _move_value(all_moves[s][best_i], e)
            for i, move in enumerate(all_moves[s]):
                if not _safe(move):
                    continue
                v = all_costs[s][i] + _move_value(move, e)
                if (v < best_c) if minimizing else (v > best_c):
                    best_i, best_c = i, v
            if best_i != policy[s]:
                policy[s] = best_i
                changed = True
        if not changed:
            return e[init]
