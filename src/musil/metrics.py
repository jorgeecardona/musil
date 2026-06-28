"""State-space metrics — how big and how branchy a design's reachable behaviour is.

Inspired by "expression cardinality" (given a semantic intent, how many valid programs express it?):
for a *design* we don't have to guess a per-language score — musil already enumerates the whole
reachable state graph, so we can MEASURE the exact analog on the behaviour itself.

- ``state_space_metrics`` reports the size and branching of a model: reachable states, transitions,
  terminals, and per-state branching (distinct successors, self-loops excluded — an ``Idle`` action
  shouldn't read as a choice). Lower branching + a tighter state space = a more deterministic, more
  reviewable design. A blow-up is the MDD "design for modelability" smell: behaviour you can't reason
  about, to reshape *before* it hides a bug.
- ``solution_cardinality`` answers the cardinality question directly: how many reachable states
  satisfy a goal. Exact over the explored space, not a guessed 1-10.

Deliberately NOT a single fabricated "determinism score" — these are honest counts on your model.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass

from musil.core import Graph, Model, explore


@dataclass(frozen=True, slots=True)
class StateSpaceMetrics:
    """The shape of a model's reachable behaviour. ``mean_branching``/``max_branching`` count DISTINCT
    successor states (excluding self-loops) — the real fan-out of choices; ``terminal_states`` have
    none. ``truncated`` means the ``max_states`` cap was hit, so the counts are lower bounds."""

    reachable_states: int
    transitions: int
    initial_states: int
    terminal_states: int
    max_branching: int
    mean_branching: float
    truncated: bool

    def __str__(self) -> str:
        cap = " (TRUNCATED — counts are lower bounds)" if self.truncated else ""
        return (
            f"{self.reachable_states} states, {self.transitions} transitions{cap}\n"
            f"  branching: mean {self.mean_branching:.2f}, max {self.max_branching} "
            f"(distinct successors, self-loops excluded)\n"
            f"  {self.initial_states} initial, {self.terminal_states} terminal"
        )


def metrics_of[S: Hashable](graph: Graph[S]) -> StateSpaceMetrics:
    """Compute metrics from an already-explored :class:`~musil.core.Graph`."""
    states = graph.states
    n = len(states)
    successors = [
        {nxt for _, nxt in graph.edges.get(s, ()) if nxt != s} for s in states
    ]
    degrees = [len(succ) for succ in successors]
    return StateSpaceMetrics(
        reachable_states=n,
        transitions=sum(len(graph.edges.get(s, ())) for s in states),
        initial_states=len(graph.initial),
        terminal_states=sum(1 for d in degrees if d == 0),
        max_branching=max(degrees, default=0),
        mean_branching=(sum(degrees) / n if n else 0.0),
        truncated=graph.truncated,
    )


def state_space_metrics[S: Hashable](
    model: Model[S], *, max_states: int = 1_000_000
) -> StateSpaceMetrics:
    """Explore ``model`` and report the size + branching of its reachable behaviour (see
    :class:`StateSpaceMetrics`)."""
    return metrics_of(explore(model, max_states=max_states))


def solution_cardinality[S: Hashable](
    model: Model[S], predicate: Callable[[S], bool], *, max_states: int = 1_000_000
) -> int:
    """How many REACHABLE states satisfy ``predicate`` — the design's "expression cardinality" for
    that intent, counted exactly over the explored state space (not a guessed score). A large number
    for a goal that *should* be reached one way is a redundancy/ambiguity smell; for a recovery goal,
    more satisfying states can mean more resilience. Interpret in context."""
    return sum(1 for s in explore(model, max_states=max_states).states if predicate(s))
