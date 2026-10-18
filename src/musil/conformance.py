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

import time
from collections.abc import Awaitable, Callable, Generator, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from inspect import isawaitable
from typing import cast

from musil.core import Graph, Model, Step, explore

__all__ = [
    "Checkpoint",
    "ConformanceResult",
    "Convergence",
    "ConvergenceMonitor",
    "Divergence",
    "ScenarioResult",
    "areplay",
    "assert_converged",
    "assert_scenarios",
    "drive_scenarios",
    "generate_traces",
    "replay",
]


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


# --- Convergence: watching an eventually-consistent real system settle --------------------------
#
# `replay` checks a system that moves in LOCK-STEP with the model: apply one action, project, compare
# NOW. An eventually-consistent system does not oblige — after a fault it churns (gossip rounds,
# retries, suspicion timeouts) and only SETTLES on the goal after a while, through intermediate states
# that are not wrong, just not-yet-converged. The question there is "within T, does the observed system
# reach a state satisfying P, allowing stutter in between", which is what paas's hand-rolled meshlab.py
# (`wait_for` + `views`) asks of a real SWIM mesh. `ConvergenceMonitor` is that question, generalized:
# observe each node, MERGE the per-node observations into one global state, poll until a goal holds or a
# deadline passes. (#33 needs 1 + 3; the FaultSchedule-driven and generate_traces-driven harness are
# separate.)


@dataclass(frozen=True, slots=True)
class Convergence[G]:
    """The outcome of watching a system settle toward a goal. ``observed`` is the last merged global
    state seen — the evidence, and on a timeout the thing to print to see how far it got."""

    converged: bool
    goal: str
    elapsed: float
    polls: int
    observed: G | None

    def __bool__(self) -> bool:
        return self.converged

    def __str__(self) -> str:
        if self.converged:
            return f"CONVERGED on {self.goal!r} after {self.elapsed:.3f}s ({self.polls} polls)"
        return (
            f"DID NOT CONVERGE on {self.goal!r} within {self.elapsed:.3f}s ({self.polls} polls)\n"
            f"  last observed: {self.observed}"
        )


class ConvergenceMonitor[N: Hashable, O, G]:
    """Watch an eventually-consistent system reach a goal, allowing churn before it does.

    ``observe(node)`` reads one node's local view (returning whatever that node reports — an empty view
    for a node that is down is normal, as in meshlab's per-node JSON dump). ``merge(views)`` assembles
    the per-node views, keyed by node, into one global abstract state — the ``views()`` step that single
    ``project`` in :func:`replay` cannot express. ``wait`` then polls that global state until a goal
    predicate holds or a deadline passes.

    ``clock``/``sleep`` are injected so the poll loop is testable on a virtual clock (no real waiting)
    and so a caller can drive it off a simulation clock; they default to wall time."""

    def __init__(
        self,
        nodes: Sequence[N],
        *,
        observe: Callable[[N], O],
        merge: Callable[[Mapping[N, O]], G],
    ) -> None:
        self._nodes = tuple(nodes)
        self._observe = observe
        self._merge = merge

    def snapshot(self) -> G:
        """Observe every node once and merge into the current global state."""
        return self._merge({node: self._observe(node) for node in self._nodes})

    def wait(
        self,
        goal: Callable[[G], bool],
        *,
        within: float,
        goal_name: str = "goal",
        poll: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Convergence[G]:
        """Poll ``snapshot()`` until ``goal`` holds (converged) or ``within`` seconds pass (did not).
        Observes at least once; returns as soon as the goal holds, so a system already at the goal
        converges in one poll with no sleeping."""
        start = clock()
        deadline = start + within
        polls = 0
        observed: G | None = None
        while True:
            observed = self.snapshot()
            polls += 1
            if goal(observed):
                return Convergence(True, goal_name, clock() - start, polls, observed)
            if clock() >= deadline:
                return Convergence(False, goal_name, clock() - start, polls, observed)
            sleep(poll)


def assert_converged[G](result: Convergence[G], *, message: str | None = None) -> None:
    """Assert a :class:`Convergence` converged — a clean pytest failure (with the last observed global
    state) when the system did not settle in time, the way ``assert_ok`` reports a model counterexample.
    Pass the result of :meth:`ConvergenceMonitor.wait`."""
    __tracebackhide__ = True
    if not result.converged:
        raise AssertionError(f"{message}\n{result}" if message else str(result))


# --- The scenario-driver: generate the harness from the model (#33 need 4) ----------------------
#
# `replay` drives the real system through `generate_traces` output and compares LOCK-STEP. An
# eventually-consistent system needs the convergence version: walk the same traces, but each step is
# a CONVERGENCE CHECKPOINT — a per-action callback drives the real fleet (meshlab's `procs[3].kill()`
# and `ip link set ... down`, keyed on the model's action name), then poll the `ConvergenceMonitor`
# until the observed global view matches the model-predicted state, allowing churn in between. This is
# the piece that keeps meshlab's hand-transcribed scenario list (A. CONVERGENCE / B. DEATH /
# C. PARTITION / D. HEAL+REJOIN) in sync with the model: the scenarios ARE the model's traces, so the
# harness is generated, not kept in sync by hand.


@dataclass(frozen=True, slots=True)
class Checkpoint[S: Hashable, G]:
    """One convergence checkpoint reached while driving a trace: after ``action`` (step ``step_index``
    of trace ``trace_index``), the model predicted ``expected`` and the real system was watched to see
    if it settled there. ``convergence`` is the :class:`Convergence` outcome — converged or not, with
    the last observed global view as the evidence."""

    trace_index: int
    step_index: int
    action: str
    expected: S
    convergence: Convergence[G]


@dataclass(frozen=True, slots=True)
class ScenarioResult[S: Hashable, G]:
    """The outcome of driving every trace. ``ok`` is True when every checkpoint converged; otherwise
    ``failure`` is the first checkpoint that did not settle in time."""

    ok: bool
    traces_run: int
    checkpoints: int
    failure: Checkpoint[S, G] | None = None

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return (
                f"ALL CONVERGED -- {self.traces_run} traces, {self.checkpoints} checkpoints, "
                f"every one settled"
            )
        f = self.failure
        assert f is not None
        return (
            f"DID NOT CONVERGE in trace {f.trace_index} at step {f.step_index} after '{f.action}':\n"
            f"  model expected: {f.expected}\n"
            f"  {f.convergence}\n"
            f"({self.traces_run} traces, {self.checkpoints} checkpoints run)"
        )


def drive_scenarios[S: Hashable, N: Hashable, O, G](
    traces: Iterable[Sequence[Step[S]]],
    *,
    monitor: ConvergenceMonitor[N, O, G],
    apply_action: Callable[[str], None],
    matches: Callable[[G, S], bool],
    within: float,
    reset: Callable[[], None] | None = None,
    checkpoint: Callable[[Step[S]], bool] = lambda _step: True,
    poll: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ScenarioResult[S, G]:
    """Drive a real eventually-consistent system through ``generate_traces`` output, convergence-checking
    each step instead of comparing lock-step. For each trace: ``reset()`` (if given) puts the real
    system back to the starting scenario; then for each step ``apply_action(step.action)`` drives the
    real fleet (the ``<init>`` step at index 0 applies nothing — it is the starting scenario) and, when
    ``checkpoint(step)`` holds, :meth:`ConvergenceMonitor.wait` polls until ``matches(observed, expected)``
    — the observed merged global view against the model-predicted state — or ``within`` seconds pass.

    The first checkpoint that does not converge stops the run and is returned as ``failure``; otherwise
    every checkpoint settled. ``matches`` takes the observed global view first and the model-predicted
    state second. ``checkpoint`` selects which steps are checkpoints (default: all), for a model whose
    intermediate steps are not settle points. ``clock``/``sleep`` are forwarded to ``wait`` so the whole
    driver runs on a virtual clock in tests."""
    traces_run = 0
    checkpoints = 0
    for trace_index, trace in enumerate(traces):
        if not trace:
            continue
        traces_run += 1
        if reset is not None:
            reset()
        for step_index, step in enumerate(trace):
            if step_index > 0:
                apply_action(step.action)
            if not checkpoint(step):
                continue
            expected = step.state
            conv = monitor.wait(
                lambda g, expected=expected: matches(g, expected),
                within=within,
                goal_name=str(expected),
                poll=poll,
                clock=clock,
                sleep=sleep,
            )
            checkpoints += 1
            if not conv.converged:
                return ScenarioResult(
                    ok=False,
                    traces_run=traces_run,
                    checkpoints=checkpoints,
                    failure=Checkpoint(trace_index, step_index, step.action, expected, conv),
                )
    return ScenarioResult(ok=True, traces_run=traces_run, checkpoints=checkpoints)


def assert_scenarios[S: Hashable, G](
    result: ScenarioResult[S, G], *, message: str | None = None
) -> None:
    """Assert every checkpoint converged — a clean pytest failure (naming the trace, step, action, the
    model-predicted state and the last observed global view) when the real system did not settle in
    time. Pass the result of :func:`drive_scenarios`."""
    __tracebackhide__ = True
    if not result.ok:
        raise AssertionError(f"{message}\n{result}" if message else str(result))


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


def _drive[S: Hashable](
    traces: Iterable[Sequence[Step[S]]],
) -> Generator[tuple[bool, str, S], S, ConformanceResult[S]]:
    """The replay loop with the I/O taken out. It yields ``(restart, action, expected)`` -- "put the
    real system back at ``start``" when ``restart``, else "apply ``action``" -- and is sent back the
    projected model state. ``replay`` drives it with plain calls and ``areplay`` with awaits, so the
    trace bookkeeping, the step counters and the divergence report are written once and cannot drift
    between the two."""
    steps_run = 0
    traces_run = 0
    for ti, trace in enumerate(traces):
        traces_run += 1
        if not trace:
            continue
        actual = yield (True, "<init>", trace[0].state)
        if actual != trace[0].state:
            return ConformanceResult(
                ok=False,
                traces_run=traces_run,
                steps_run=steps_run,
                divergence=Divergence(ti, 0, "<init>", trace[0].state, actual),
            )
        for si in range(1, len(trace)):
            step = trace[si]
            actual = yield (False, step.action, step.state)
            steps_run += 1
            if actual != step.state:
                return ConformanceResult(
                    ok=False,
                    traces_run=traces_run,
                    steps_run=steps_run,
                    divergence=Divergence(ti, si, step.action, step.state, actual),
                )
    return ConformanceResult(ok=True, traces_run=traces_run, steps_run=steps_run)


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
    trace's initial state. Use ``areplay`` when the real system is async."""
    driver = _drive(traces)
    real = start
    try:
        restart, action, _expected = next(driver)
        while True:
            real = start if restart else step_fn(real, action)
            restart, action, _expected = driver.send(project(real))
    except StopIteration as stop:
        result: ConformanceResult[S] = stop.value
        return result


async def areplay[R, S: Hashable](
    traces: Iterable[Sequence[Step[S]]],
    *,
    step_fn: Callable[[R, str], Awaitable[R]],
    project: Callable[[R], S] | Callable[[R], Awaitable[S]],
    start: R,
) -> ConformanceResult[S]:
    """``replay`` for an async implementation: ``step_fn`` is awaited, and ``project`` may be either
    sync or a coroutine function (awaited when it returns an awaitable). Same arguments, same
    ``ConformanceResult``, same divergence indices -- it drives the same loop as ``replay``.

    This exists because the sync ``replay`` forces one ``asyncio.run`` per step, which cannot be
    called from a running loop (so no ``async def`` test can use it) and, worse, gives every step its
    own event loop: a connection pool or an open transaction created in one step is dead in the next.
    Awaiting inside one loop keeps that loop-scoped state alive across a whole trace."""
    driver = _drive(traces)
    real = start
    try:
        restart, action, _expected = next(driver)
        while True:
            real = start if restart else await step_fn(real, action)
            # project may be sync or async; awaiting loses S through isawaitable's TypeGuard
            # (Awaitable[Any]), so the cast restores what the signature already promised.
            candidate = project(real)
            projected = cast("S", await candidate) if isawaitable(candidate) else candidate
            restart, action, _expected = driver.send(projected)
    except StopIteration as stop:
        result: ConformanceResult[S] = stop.value
        return result
