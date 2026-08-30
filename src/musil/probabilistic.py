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
reach the target in a DTMC, finite only when the target is reached almost surely. See PROBABILISTIC_NOTES.md.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from fractions import Fraction
from typing import Literal

from musil.core import Action, Model, actions_source, explore

# A distribution over successors: (probability, successor) pairs summing to 1 (empty = absorbing / no move).
type _Dist[S] = list[tuple[Fraction, S]]

# A moves function: given a state and its enabled actions, return the moves a scheduler picks between. Each
# move is a group of actions whose weights form one probability distribution over successors. A singleton
# group is a Dirac move; grouping every enabled action into one move recovers the DTMC (no nondeterminism).
type Moves[S] = Callable[[S, tuple[Action[S], ...]], Iterable[Sequence[Action[S]]]]


def _uniform(_name: str, _s: object) -> int:
    return 1


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
    pairs = [(Fraction(weight(name, state)), nxt) for name, nxt in contributions]
    total = sum((wt for wt, _ in pairs), Fraction(0))
    if total == 0:
        return []
    acc: dict[S, Fraction] = {}
    for wt, nxt in pairs:
        acc[nxt] = acc.get(nxt, Fraction(0)) + wt / total
    return [(p, t) for t, p in acc.items()]


def reach_probability[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    steps: int | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact probability of eventually reaching a ``target`` state from the model's initial state,
    treating the reachable graph as a DTMC.

    At each state the enabled actions' ``weight(action_name, state)`` values are normalised into a
    probability distribution over the successors (edges to the same successor sum); the default weight is
    ``1`` for every action, i.e. a uniform choice. States must be HASHABLE (the graph is explored). Returns
    a ``fractions.Fraction`` — exact, no floating point.

    With ``steps=k`` the answer is the probability of reaching ``target`` WITHIN ``k`` transitions (an exact
    finite unrolling; ``steps=0`` is the indicator of ``target``). With ``steps=None`` (the default) it is
    the unbounded probability, solved by the exact linear system. Raises ``ValueError`` if the exploration
    truncates at ``max_states`` (the probability would be inconclusive) or if ``steps`` is negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("reach_probability: exploration truncated at max_states; the probability is inconclusive")
    w = weight if weight is not None else _uniform
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
    if steps is None:
        return _dtmc_values(graph.states, dist, target)[graph.initial[0]]
    if steps < 0:
        raise ValueError(f"reach_probability: steps must be non-negative, got {steps}")
    return _bounded_values(graph.states, {s: [dist[s]] for s in graph.states}, target, steps, minimize=False)[
        graph.initial[0]
    ]


def expected_reward[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    cost: Callable[[str, S], Fraction | int] | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact EXPECTED accumulated cost to first reach ``target`` from the model's initial state,
    treating the reachable graph as a DTMC. With the default unit ``cost`` this is the expected number of
    STEPS to reach the target.

    ``weight`` normalises the enabled actions into a distribution over successors exactly as in
    ``reach_probability``; ``cost(action_name, state)`` is the cost charged for firing that action (default
    ``1``). Returns a ``fractions.Fraction`` — exact, no floating point, solving ``E(s) = 0`` on the target
    and ``E(s) = sum_s' P(s, s') (cost + E(s'))`` elsewhere.

    The expectation is finite only if the target is reached ALMOST SURELY; otherwise it is infinite, so this
    raises ``ValueError`` when ``reach_probability`` from the initial state is not exactly 1 (a scheduler-free
    DTMC has a single value). Also raises ``ValueError`` if the exploration truncates at ``max_states``."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("expected_reward: exploration truncated at max_states; the expectation is inconclusive")
    init = graph.initial[0]
    if target(init):
        return Fraction(0)
    w = weight if weight is not None else _uniform
    c = cost if cost is not None else _uniform  # default cost 1 per step -> expected number of steps
    dist = {s: _normalize(graph.edges.get(s, ()), s, w) for s in graph.states}
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
        total = sum(Fraction(w(name, s)) for name, _ in edges)
        for name, nxt in edges:
            p = Fraction(w(name, s)) / total
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


def reach_probability_mdp[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    moves: Moves[S],
    weight: Callable[[str, S], Fraction | int] | None = None,
    optimize: Literal["max", "min"] = "max",
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

    With ``steps=k`` the answer is instead the optimal probability of reaching ``target`` WITHIN ``k``
    transitions — an exact finite backward induction, so ``_s0_min`` is not needed (a bounded horizon cannot
    stall). Raises ``ValueError`` if the exploration truncates at ``max_states`` or if ``steps`` is
    negative."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("reach_probability_mdp: exploration truncated at max_states; the probability is inconclusive")
    source = actions_source(model)
    w = weight if weight is not None else _uniform
    # Per state, the moves as normalized distributions, using the canonical successors explore already
    # computed (group the state's edges by action name, so no canonicalization is redone here).
    all_moves: dict[S, list[_Dist[S]]] = {}
    for s in graph.states:
        by_name = {name: nxt for name, nxt in graph.edges.get(s, ())}
        enabled = tuple(a for a in source(s) if a.enabled(s))
        state_moves = [
            _normalize([(a.name, by_name[a.name]) for a in group if a.name in by_name], s, w)
            for group in moves(s, enabled)
        ]
        all_moves[s] = state_moves if state_moves else [[]]  # no move -> a single absorbing move
    minimize = optimize == "min"
    if steps is not None:
        if steps < 0:
            raise ValueError(f"reach_probability_mdp: steps must be non-negative, got {steps}")
        return _bounded_values(graph.states, all_moves, target, steps, minimize)[graph.initial[0]]
    # For min, pin the "can avoid the target forever" states to 0 by making them absorbing before iterating;
    # for max they need no special treatment (unreachable-to-target already resolves to 0 in _dtmc_values).
    absorbing = _s0_min(graph.states, all_moves, target) if minimize else set[S]()
    # Policy iteration. Each improvement switches a state only to a STRICTLY better move (larger for max,
    # smaller for min) under the current exact values, so the values move monotonically and no policy
    # repeats -> it terminates (the policy space is finite). Start every state at its first move.
    policy: dict[S, int] = dict.fromkeys(graph.states, 0)
    while True:
        dist = {s: ([] if s in absorbing else all_moves[s][policy[s]]) for s in graph.states}
        values = _dtmc_values(graph.states, dist, target)
        changed = False
        for s in graph.states:
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
            return values[graph.initial[0]]
