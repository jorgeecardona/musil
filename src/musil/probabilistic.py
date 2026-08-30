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
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from fractions import Fraction

from musil.core import Model, explore, reaches


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


def reach_probability[S: Hashable](
    model: Model[S],
    target: Callable[[S], bool],
    *,
    weight: Callable[[str, S], Fraction | int] | None = None,
    max_states: int = 1_000_000,
) -> Fraction:
    """The exact probability of eventually reaching a ``target`` state from the model's initial state,
    treating the reachable graph as a DTMC.

    At each state the enabled actions' ``weight(action_name, state)`` values are normalised into a
    probability distribution over the successors (edges to the same successor sum); the default weight is
    ``1`` for every action, i.e. a uniform choice. States must be HASHABLE (the graph is explored). Returns
    a ``fractions.Fraction`` — exact, no floating point. Raises ``ValueError`` if the exploration truncates
    at ``max_states`` (the probability would be inconclusive) or if a non-target state has zero total
    weight only because ``weight`` returned all-zero (an ill-formed distribution)."""
    graph = explore(model, max_states=max_states)
    if graph.truncated:
        raise ValueError("reach_probability: exploration truncated at max_states; the probability is inconclusive")
    def _uniform(_name: str, _s: S) -> int:
        return 1

    w = weight if weight is not None else _uniform
    can_reach = reaches(graph, target)  # states from which a target is reachable; else probability 0
    unknown = [s for s in graph.states if not target(s) and s in can_reach]
    index = {s: i for i, s in enumerate(unknown)}
    n = len(unknown)
    a = [[Fraction(0) for _ in range(n)] for _ in range(n)]
    b = [Fraction(0) for _ in range(n)]
    for s in unknown:
        i = index[s]
        a[i][i] = Fraction(1)
        edges = graph.edges.get(s, ())
        total = sum(Fraction(w(name, s)) for name, _ in edges)
        if total == 0:
            continue  # absorbing non-target: probability 0 (x_i = 0)
        for name, nxt in edges:
            p = Fraction(w(name, s)) / total
            if target(nxt):
                b[i] += p
            elif nxt in index:
                a[i][index[nxt]] -= p
            # else nxt cannot reach the target -> contributes 0
    solution = _solve_linear(a, b)
    init = graph.initial[0]
    if target(init):
        return Fraction(1)
    if init not in index:
        return Fraction(0)  # the initial state cannot reach the target
    return solution[index[init]]
