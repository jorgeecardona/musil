"""Conformance: generate traces from a model, replay against a (real-ish) implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

import pytest

from musil import Action, Model
from musil.conformance import ConformanceResult, areplay, generate_traces, replay


@dataclass(frozen=True)
class Light:
    color: str = "red"


MODEL = Model(
    init=Light("red"),
    actions=[
        Action("go", lambda s: s.color == "red", lambda s: replace(s, color="green")),
        Action("slow", lambda s: s.color == "green", lambda s: replace(s, color="yellow")),
        Action("stop", lambda s: s.color == "yellow", lambda s: replace(s, color="red")),
    ],
)

# the "real implementation": a plain string-state machine, independent of the model dataclass
_NEXT = {"go": ("red", "green"), "slow": ("green", "yellow"), "stop": ("yellow", "red")}


def _correct_step(color: str, action: str) -> str:
    src, dst = _NEXT[action]
    return dst if color == src else color


def _buggy_step(color: str, action: str) -> str:
    if action == "go" and color == "red":
        return "yellow"  # BUG: red --go--> yellow instead of green
    return _correct_step(color, action)


def test_edge_traces_cover_every_transition() -> None:
    traces = generate_traces(MODEL, cover="edges")
    # one trace per reachable edge; the light has 3 edges
    assert len(traces) == 3
    assert all(t[0].action == "<init>" for t in traces)


def test_correct_implementation_conforms() -> None:
    traces = generate_traces(MODEL, cover="edges")
    result = replay(
        traces,
        step_fn=_correct_step,
        project=lambda color: Light(color),
        start="red",
    )
    assert result.ok, str(result)
    assert result.steps_run > 0


def test_buggy_implementation_is_caught() -> None:
    traces = generate_traces(MODEL, cover="edges")
    result = replay(
        traces,
        step_fn=_buggy_step,
        project=lambda color: Light(color),
        start="red",
    )
    assert not result.ok
    d = result.divergence
    assert d is not None
    assert d.action == "go"
    assert d.expected == Light("green") and d.actual == Light("yellow")


def test_projection_mismatch_at_init_is_caught() -> None:
    traces = generate_traces(MODEL, cover="states")
    result = replay(
        traces, step_fn=_correct_step, project=lambda color: Light(color), start="green"
    )
    assert not result.ok
    assert result.divergence is not None and result.divergence.step_index == 0


# --- areplay: driving an async implementation -------------------------------------------------


class _Conn:
    """The long-lived resource the async path exists to protect: it is bound to the event loop that
    opened it, exactly as a connection pool or an open transaction is. Using it from another loop is
    an error here rather than a subtle misbehaviour, so a test that accidentally creates a loop per
    step fails loudly."""

    def __init__(self, *, buggy: bool = False) -> None:
        self.buggy = buggy
        self.loop: asyncio.AbstractEventLoop | None = None
        self.steps = 0

    async def open(self) -> _Conn:
        self.loop = asyncio.get_running_loop()
        return self

    async def apply(self, color: str, action: str) -> str:
        await asyncio.sleep(0)  # a real await, so this cannot be driven synchronously
        if self.loop is not asyncio.get_running_loop():
            raise RuntimeError("stepped from a different event loop than the one that opened the connection")
        self.steps += 1
        return _buggy_step(color, action) if self.buggy else _correct_step(color, action)


@dataclass(frozen=True)
class _Handle:
    """What travels through areplay: the shared connection plus this run's state. Immutable, so
    restarting a trace from ``start`` really does restart it."""

    conn: _Conn
    color: str = "red"


async def _astep(h: _Handle, action: str) -> _Handle:
    return _Handle(h.conn, await h.conn.apply(h.color, action))


async def _aproject(h: _Handle) -> Light:
    await asyncio.sleep(0)  # reading the real system awaits too
    return Light(h.color)


def test_areplay_conforms_and_keeps_one_connection_across_the_whole_run() -> None:
    async def main() -> tuple[ConformanceResult[Light], _Conn]:
        conn = await _Conn().open()
        result = await areplay(
            generate_traces(MODEL, cover="edges"),
            step_fn=_astep,
            project=_aproject,
            start=_Handle(conn),
        )
        return result, conn

    result, conn = asyncio.run(main())
    assert result.ok, str(result)
    # every step ran on the loop that opened the connection -- apply() raises otherwise
    assert conn.steps == result.steps_run > 0


def test_areplay_reports_the_same_divergence_as_replay() -> None:
    traces = generate_traces(MODEL, cover="edges")
    sync_result = replay(traces, step_fn=_buggy_step, project=lambda c: Light(c), start="red")

    async def main() -> ConformanceResult[Light]:
        conn = await _Conn(buggy=True).open()
        return await areplay(traces, step_fn=_astep, project=_aproject, start=_Handle(conn))

    async_result = asyncio.run(main())
    assert not sync_result.ok and not async_result.ok
    a, b = sync_result.divergence, async_result.divergence
    assert a is not None and b is not None
    assert (a.trace_index, a.step_index, a.action) == (b.trace_index, b.step_index, b.action)
    assert (a.expected, a.actual) == (b.expected, b.actual)
    assert sync_result.steps_run == async_result.steps_run


def test_areplay_accepts_a_sync_project() -> None:
    async def main() -> ConformanceResult[Light]:
        conn = await _Conn().open()
        return await areplay(
            generate_traces(MODEL, cover="edges"),
            step_fn=_astep,
            project=lambda h: Light(h.color),  # plain sync projection, never awaited
            start=_Handle(conn),
        )

    assert asyncio.run(main()).ok


def test_the_asyncio_run_per_step_workaround_fails_inside_a_running_loop() -> None:
    """Why areplay exists: the sync replay can only drive async code with one asyncio.run per step,
    and that raises the moment the test itself is a coroutine."""

    async def one_step(color: str, action: str) -> str:
        await asyncio.sleep(0)
        return _correct_step(color, action)

    def step_fn(color: str, action: str) -> str:
        coro = one_step(color, action)
        try:
            return asyncio.run(coro)
        finally:
            coro.close()  # asyncio.run raised before starting it; close it so gc stays quiet

    async def main() -> ConformanceResult[Light]:
        return replay(
            generate_traces(MODEL, cover="edges"),
            step_fn=step_fn,
            project=lambda color: Light(color),
            start="red",
        )

    with pytest.raises(RuntimeError, match="cannot be called from a running event loop"):
        asyncio.run(main())
