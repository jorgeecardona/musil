"""Refinement: does a run of the real system refine the model?

Conformance (conformance.py) drives the real code with model-generated *action labels*. Refinement is
the other direction: take a sequence of *observed* concrete states (e.g. snapshots from a simulation
run of the real code) and check each transition is a legal step of the model -- a stutter (no change
to the abstract state) or an edge the model allows. This is the runtime analog of seL4-style
refinement, and the oracle musil.sim uses to hold real code to a spec."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from musil import Action, Model
from musil.refine import RefinementMonitor, acheck_refinement, check_refinement


@dataclass(frozen=True)
class N:
    v: int = 0


def _counter() -> Model[N]:
    # 0 -> 1 -> 2, then 2 is an absorbing sink
    return Model(
        init=N(0),
        actions=[Action("inc", lambda s: s.v < 2, lambda s: N(s.v + 1))],
        terminal=lambda s: s.v == 2,
    )


def test_a_faithful_run_refines_the_model() -> None:
    result = check_refinement(_counter(), [N(0), N(1), N(2)], lambda c: c)
    assert result.ok, str(result)
    assert result.steps_checked == 3


def test_stuttering_is_allowed() -> None:
    # repeated identical abstract states are no-ops (stuttering-invariance), not violations
    result = check_refinement(_counter(), [N(0), N(0), N(1), N(1), N(2), N(2)], lambda c: c)
    assert result.ok, str(result)


def test_a_skipped_step_is_caught() -> None:
    # 0 -> 2 is not a model edge; refinement must reject it
    result = check_refinement(_counter(), [N(0), N(2)], lambda c: c)
    assert not result.ok
    assert result.violation is not None
    assert result.violation.reason == "no-model-step"
    assert result.violation.abstract_from == N(0)
    assert result.violation.abstract_to == N(2)


def test_a_state_outside_the_model_is_caught() -> None:
    result = check_refinement(_counter(), [N(0), N(5)], lambda c: c)
    assert not result.ok
    assert result.violation is not None
    assert result.violation.reason == "unknown-state"


def test_bad_initial_state_is_caught_unless_init_check_disabled() -> None:
    # starting at N(1) isn't the model's init...
    bad = check_refinement(_counter(), [N(1), N(2)], lambda c: c)
    assert bad.violation is not None and bad.violation.reason == "bad-init"
    # ...but as a mid-run fragment (1 -> 2 is a real edge) it refines
    assert check_refinement(_counter(), [N(1), N(2)], lambda c: c, require_init=False).ok


def test_abstraction_maps_concrete_state_to_the_model() -> None:
    # the real system's state is a bare int; the abstraction lifts it into the model's space
    result = check_refinement(_counter(), [0, 1, 2], lambda c: N(c))
    assert result.ok, str(result)


def test_monitor_streams_one_observation_at_a_time() -> None:
    mon: RefinementMonitor[N, N] = RefinementMonitor(_counter(), lambda c: c)
    assert mon.observe(N(0)) is None
    assert mon.observe(N(1)) is None
    v = mon.observe(N(0))  # 1 -> 0 is not a model edge
    assert v is not None and v.reason == "no-model-step"


# --- async: an observation source that has to be awaited --------------------------------------


async def _poll(values: list[int]) -> AsyncIterator[N]:
    """An async source of observations -- a live service polled step by step, not a list collected
    up front."""
    for v in values:
        await asyncio.sleep(0)
        yield N(v)


async def _aabstract(c: N) -> N:
    """An abstraction that has to read the real system, so it awaits."""
    await asyncio.sleep(0)
    return c


def test_acheck_refinement_accepts_a_faithful_async_run() -> None:
    result = asyncio.run(acheck_refinement(_counter(), _poll([0, 1, 2]), _aabstract))
    assert result.ok, str(result)
    assert result.steps_checked == 3


def test_acheck_refinement_catches_a_skipped_step() -> None:
    result = asyncio.run(acheck_refinement(_counter(), _poll([0, 2]), _aabstract))
    assert not result.ok
    assert result.violation is not None
    assert result.violation.reason == "no-model-step"


def test_acheck_refinement_matches_the_sync_result() -> None:
    observations = [0, 1, 1, 2]
    sync = check_refinement(_counter(), [N(v) for v in observations], lambda c: c)
    asyn = asyncio.run(acheck_refinement(_counter(), _poll(observations), _aabstract))
    assert (sync.ok, sync.steps_checked) == (asyn.ok, asyn.steps_checked)


def test_acheck_refinement_accepts_a_sync_abstraction() -> None:
    result = asyncio.run(acheck_refinement(_counter(), _poll([0, 1, 2]), lambda c: c))
    assert result.ok, str(result)


def test_acheck_refinement_stops_polling_at_the_first_violation() -> None:
    """The reason for streaming rather than collecting: a violation must stop the source, not be
    found after the whole (possibly unbounded) run has been drained."""
    polled: list[int] = []

    async def source() -> AsyncIterator[N]:
        for v in (0, 2, 1, 2):
            polled.append(v)
            await asyncio.sleep(0)
            yield N(v)

    result = asyncio.run(acheck_refinement(_counter(), source(), _aabstract))
    assert not result.ok
    assert polled == [0, 2]  # the source was never asked for the rest


def test_observe_refuses_an_async_abstraction_instead_of_reporting_a_bogus_violation() -> None:
    monitor: RefinementMonitor[N, N] = RefinementMonitor(_counter(), _aabstract)
    with pytest.raises(TypeError, match="aobserve"):
        monitor.observe(N(0))
