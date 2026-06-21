"""Conformance: does the real implementation behave like the model?

Model checking proves the *design* is sound. Conformance testing checks the *code matches the
design*: generate action traces from the model (sequences that cover the reachable graph), then
replay each against the real system through a thin adapter, asserting the implementation lands in the
state the model predicted after every step. It does not *prove* refinement (that's theorem-proving
territory), but it *checks* it exhaustively over the model's traces against the running code — the
practical "implementation faithful to spec" bridge (see docs/specs/RESEARCH.md: P, Stateright, ioco).

Two pieces:
  - ``generate_traces(model)`` -> action sequences (lists of Steps, ``<init>`` first) that together
    cover every reachable edge (or state).
  - ``replay(model, traces, step_fn, project, start)`` -> ConformanceResult. ``step_fn(real, action)``
    drives the real system; ``project(real)`` maps it back to a model state to compare. The first
    divergence (real projected state != model-predicted state) is reported."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass

from musil.core import Graph, Model, Step, explore


@dataclass(frozen=True, slots=True)
class Divergence[S: Hashable]:
    """The implementation departed from the model: after ``action`` (step ``step_index`` of trace
    ``trace_index``), the model predicted ``expected`` but the implementation projected to ``actual``."""

    trace_index: int
    step_index: int
    action: str
    expected: S
    actual: S


@dataclass(frozen=True, slots=True)
class ConformanceResult[S: Hashable]:
    ok: bool
    traces_run: int
    steps_run: int
    divergence: Divergence[S] | None = None

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return f"CONFORMS -- {self.traces_run} traces, {self.steps_run} steps, no divergence"
        d = self.divergence
        assert d is not None
        return (
            f"DIVERGENCE in trace {d.trace_index} at step {d.step_index} after '{d.action}':\n"
            f"  model expected: {d.expected}\n"
            f"  implementation: {d.actual}\n"
            f"({self.traces_run} traces, {self.steps_run} steps run)"
        )


def _paths[S: Hashable](g: Graph[S]) -> tuple[dict[S, tuple[S, str] | None], list[S]]:
    parent: dict[S, tuple[S, str] | None] = {}
    order: list[S] = []
    for s in g.initial:
        if s not in parent:
            parent[s] = None
            order.append(s)
    head = 0
    while head < len(order):
        s = order[head]
        head += 1
        for a, t in g.edges[s]:
            if t not in parent:
                parent[t] = (s, a)
                order.append(t)
    return parent, order


def _path_to[S: Hashable](parent: dict[S, tuple[S, str] | None], state: S) -> tuple[Step[S], ...]:
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


def generate_traces[S: Hashable](
    model: Model[S], *, cover: str = "edges", max_traces: int = 100_000, max_states: int = 1_000_000
) -> list[tuple[Step[S], ...]]:
    """Action sequences from the reachable graph (each a tuple of Steps, ``<init>`` first). With
    ``cover='edges'`` (default) the set exercises every reachable transition at least once; with
    ``cover='states'``, a shortest path to each reachable state. Each trace is a shortest stem, so
    replays stay short."""
    g = explore(model, max_states=max_states)
    parent, order = _paths(g)
    traces: list[tuple[Step[S], ...]] = []
    if cover == "states":
        for s in order:
            traces.append(_path_to(parent, s))
            if len(traces) >= max_traces:
                break
        return traces
    for s in order:
        base = _path_to(parent, s)
        for action, t in g.edges[s]:
            traces.append((*base, Step(action=action, state=t)))
            if len(traces) >= max_traces:
                return traces
    return traces


def replay[R, S: Hashable](
    traces: Iterable[Sequence[Step[S]]],
    *,
    step_fn: Callable[[R, str], R],
    project: Callable[[R], S],
    start: R,
) -> ConformanceResult[S]:
    """Replay each trace (from ``generate_traces``) against the real system. ``start`` is the real
    initial state (its projection must equal the model's initial state); ``step_fn(real, action)``
    applies an action to the real system; ``project`` maps a real state back to a model state for
    comparison. Single-initial-state models; for multiple inits, project(start) must match each
    trace's initial state."""
    steps_run = 0
    traces_run = 0
    for ti, trace in enumerate(traces):
        traces_run += 1
        real = start
        if not trace:
            continue
        if project(real) != trace[0].state:
            return ConformanceResult(
                ok=False, traces_run=traces_run, steps_run=steps_run,
                divergence=Divergence(ti, 0, "<init>", trace[0].state, project(real)),
            )
        for si in range(1, len(trace)):
            step = trace[si]
            real = step_fn(real, step.action)
            steps_run += 1
            if project(real) != step.state:
                return ConformanceResult(
                    ok=False, traces_run=traces_run, steps_run=steps_run,
                    divergence=Divergence(ti, si, step.action, step.state, project(real)),
                )
    return ConformanceResult(ok=True, traces_run=traces_run, steps_run=steps_run)
