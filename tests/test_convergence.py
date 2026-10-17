"""ConvergenceMonitor (#33, needs 1 + 3): watch an eventually-consistent system settle toward a goal,
merging per-node views into a global state, on a virtual clock so no test actually waits."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from musil.conformance import Convergence, ConvergenceMonitor, assert_converged

ALIVE = {"n1": "alive", "n2": "alive", "n3": "alive"}
NODES: tuple[int, ...] = (1, 2, 3)


class Clock:
    """Virtual time: `sleep` just advances the clock, so poll loops run instantly and deterministically."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


class Fleet:
    """A scripted eventually-consistent system: `views_by_poll[k][node]` is node `k`'s view at poll k
    (the shape meshlab's per-node JSON dumps have). The poll advances once per full snapshot."""

    def __init__(self, views_by_poll: list[dict[int, dict[str, str]]]) -> None:
        self._views = views_by_poll
        self.poll = 0

    def observe(self, node: int) -> dict[str, str]:
        return self._views[min(self.poll, len(self._views) - 1)][node]

    def merge(self, views: Mapping[int, dict[str, str]]) -> dict[int, dict[str, str]]:
        self.poll += 1  # a full snapshot was taken; advance scripted time
        return dict(views)


def _monitor(fleet: Fleet) -> ConvergenceMonitor[int, dict[str, str], dict[int, dict[str, str]]]:
    return ConvergenceMonitor(NODES, observe=fleet.observe, merge=fleet.merge)


def _all_alive(g: dict[int, dict[str, str]]) -> bool:
    return all(g[n] == ALIVE for n in NODES)


def test_converges_after_churn() -> None:
    clock = Clock()
    fleet = Fleet(
        [
            {1: {}, 2: {}, 3: {}},  # poll 0: nothing gossiped yet
            {1: ALIVE, 2: {"n1": "alive"}, 3: {}},  # poll 1: partial, still churning
            {1: ALIVE, 2: ALIVE, 3: ALIVE},  # poll 2: converged
        ]
    )
    result = _monitor(fleet).wait(
        _all_alive,
        within=10.0,
        poll=1.0,
        goal_name="all 3 alive",
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result.converged
    assert result.polls == 3  # settled on the third snapshot
    assert result.elapsed == pytest.approx(2.0)  # two 1s sleeps between the three polls
    assert result.observed == {1: ALIVE, 2: ALIVE, 3: ALIVE}


def test_already_at_goal_converges_in_one_poll_without_sleeping() -> None:
    clock = Clock()
    fleet = Fleet([{1: ALIVE, 2: ALIVE, 3: ALIVE}])
    result = _monitor(fleet).wait(
        _all_alive, within=10.0, poll=1.0, clock=clock.now, sleep=clock.sleep
    )
    assert result.converged
    assert result.polls == 1
    assert clock.t == 0.0  # never slept


def test_times_out_and_keeps_the_last_observed_state() -> None:
    clock = Clock()
    fleet = Fleet([{1: ALIVE, 2: {"n1": "alive"}, 3: {}}])  # never fully converges
    result = _monitor(fleet).wait(
        _all_alive,
        within=5.0,
        poll=1.0,
        goal_name="all 3 alive",
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert not result.converged
    assert result.elapsed >= 5.0
    assert result.observed == {
        1: ALIVE,
        2: {"n1": "alive"},
        3: {},
    }  # the evidence of how far it got
    assert bool(result) is False


def test_merge_assembles_a_global_state_from_per_node_views() -> None:
    # a down node reports an empty view (meshlab's try/except -> {}); merge still assembles a global
    fleet = Fleet([{1: {"n2": "alive"}, 2: {"n1": "alive"}, 3: {}}])
    snapshot = _monitor(fleet).snapshot()
    assert snapshot == {1: {"n2": "alive"}, 2: {"n1": "alive"}, 3: {}}


def test_assert_converged_passes_then_raises_with_the_last_state() -> None:
    ok: Convergence[dict[int, dict[str, str]]] = Convergence(True, "goal", 1.0, 2, {1: ALIVE})
    assert_converged(ok)  # no raise

    timed_out: Convergence[dict[int, dict[str, str]]] = Convergence(
        False, "all 3 alive", 5.0, 6, {1: {}}
    )
    with pytest.raises(AssertionError, match="all 3 alive"):
        assert_converged(timed_out, message="mesh never reconverged")
