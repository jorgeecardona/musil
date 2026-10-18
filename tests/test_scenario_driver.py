"""The generate_traces-driven scenario harness (#33 need 4).

`drive_scenarios` walks the model's own traces against a real eventually-consistent system: a
per-action callback drives the real fleet, and each step is a convergence checkpoint watched through a
`ConvergenceMonitor`. These tests stand in a fake mesh that settles toward a target set after a fixed
delay, driven on a virtual clock so nothing actually sleeps."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from musil import Action, Model, Step
from musil.conformance import (
    ConvergenceMonitor,
    assert_scenarios,
    drive_scenarios,
    generate_traces,
)

NODES: tuple[str, ...] = ("a", "b")


def membership_model() -> Model[frozenset[str]]:
    """A tiny membership model: the state is the set of joined nodes; join/leave flip one node."""
    actions: list[Action[frozenset[str]]] = []
    for n in NODES:
        actions.append(
            Action(f"join:{n}", enabled=lambda s, n=n: n not in s, apply=lambda s, n=n: s | {n})
        )
        actions.append(
            Action(f"leave:{n}", enabled=lambda s, n=n: n in s, apply=lambda s, n=n: s - {n})
        )
    # init is a list of one state: a bare frozenset would read as an *iterable of* initial states.
    return Model(init=[frozenset()], actions=actions)


class Clock:
    """A virtual clock: `sleep` advances `now`, nothing blocks."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


class Mesh:
    """A fake eventually-consistent fleet. The operator drives it toward an authoritative ``intended``
    membership; every node reports that set only once ``delay`` seconds of virtual time have passed
    since the last change (the churn window), reporting the stale view until then."""

    def __init__(self, clock: Clock, *, delay: float) -> None:
        self._clock = clock
        self._delay = delay
        self._old: frozenset[str] = frozenset()
        self._intended: frozenset[str] = frozenset()
        self._converge_at = 0.0  # already settled on the empty set at t=0

    def _retarget(self, members: frozenset[str]) -> None:
        self._old = self.view("")  # whatever is believed right now becomes the stale view
        self._intended = members
        self._converge_at = self._clock.now() + self._delay

    def join(self, node: str) -> None:
        self._retarget(self._intended | {node})

    def leave(self, node: str) -> None:
        self._retarget(self._intended - {node})

    def reset(self) -> None:
        self._retarget(frozenset())

    def view(self, _node: str) -> frozenset[str]:
        return self._intended if self._clock.now() >= self._converge_at else self._old


def apply_to_mesh(mesh: Mesh, action: str) -> None:
    """Drive the real mesh by the model's action name — the caller's bridge (join:x adds x, leave:x
    removes x), exactly as meshlab keys subprocess calls off the action it is replaying."""
    verb, node = action.split(":")
    (mesh.join if verb == "join" else mesh.leave)(node)


def merge_views(views: Mapping[str, frozenset[str]]) -> frozenset[str] | None:
    """One agreed global view: the common set when every node agrees, else None (still churning)."""
    seen = set(views.values())
    return next(iter(seen)) if len(seen) == 1 else None


def monitor_over(mesh: Mesh) -> ConvergenceMonitor[str, frozenset[str], frozenset[str] | None]:
    return ConvergenceMonitor(NODES, observe=mesh.view, merge=merge_views)


def test_every_checkpoint_converges() -> None:
    clock = Clock()
    mesh = Mesh(clock, delay=5.0)
    traces = generate_traces(membership_model())
    assert traces  # guard against a vacuous pass
    result = drive_scenarios(
        traces,
        monitor=monitor_over(mesh),
        apply_action=lambda a: apply_to_mesh(mesh, a),
        matches=lambda observed, expected: observed == expected,
        within=100.0,
        reset=mesh.reset,
        poll=1.0,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result.ok
    assert result.traces_run == len(traces)
    assert result.failure is None
    assert_scenarios(result)  # does not raise


def test_slower_than_timeout_is_a_failure() -> None:
    clock = Clock()
    mesh = Mesh(clock, delay=200.0)  # settles slower than any 100s checkpoint
    result = drive_scenarios(
        generate_traces(membership_model()),
        monitor=monitor_over(mesh),
        apply_action=lambda a: apply_to_mesh(mesh, a),
        matches=lambda observed, expected: observed == expected,
        within=100.0,
        reset=mesh.reset,
        poll=1.0,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert not result.ok
    f = result.failure
    assert f is not None
    # <init>'s stale view already equals the empty target, so it converges at t=0; the first join is
    # the step that cannot settle within 100s.
    assert f.step_index == 1
    assert not f.convergence.converged
    assert "DID NOT CONVERGE" in str(result)


def test_checkpoint_selects_which_steps_are_checked() -> None:
    traces = generate_traces(membership_model())
    assert traces

    def run(checkpoint: Callable[[Step[frozenset[str]]], bool] | None) -> int:
        clock = Clock()
        mesh = Mesh(clock, delay=5.0)
        result = drive_scenarios(
            traces,
            monitor=monitor_over(mesh),
            apply_action=lambda a: apply_to_mesh(mesh, a),
            matches=lambda observed, expected: observed == expected,
            within=100.0,
            reset=mesh.reset,
            checkpoint=(lambda _step: True) if checkpoint is None else checkpoint,
            poll=1.0,
            clock=clock.now,
            sleep=clock.sleep,
        )
        assert result.ok
        return result.checkpoints

    all_steps = run(None)  # default: every step is a checkpoint
    # Skip the <init> checkpoint of every trace: exactly one fewer checkpoint per trace.
    no_init = run(lambda step: step.action != "<init>")
    assert no_init == all_steps - len(traces)
    assert no_init < all_steps


def test_reset_runs_once_per_trace() -> None:
    clock = Clock()
    mesh = Mesh(clock, delay=5.0)
    traces = generate_traces(membership_model())
    resets = 0

    def reset() -> None:
        nonlocal resets
        resets += 1
        mesh.reset()

    result = drive_scenarios(
        traces,
        monitor=monitor_over(mesh),
        apply_action=lambda a: apply_to_mesh(mesh, a),
        matches=lambda observed, expected: observed == expected,
        within=100.0,
        reset=reset,
        poll=1.0,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result.ok
    assert resets == result.traces_run


def test_init_only_trace_waits_without_applying() -> None:
    # A one-element trace (just <init>) applies no action and converges on the initial state.
    clock = Clock()
    mesh = Mesh(clock, delay=5.0)
    result = drive_scenarios(
        [(Step(action="<init>", state=frozenset[str]()),)],
        monitor=monitor_over(mesh),
        apply_action=lambda a: apply_to_mesh(mesh, a),
        matches=lambda observed, expected: observed == expected,
        within=100.0,
        poll=1.0,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert result.ok
    assert result.checkpoints == 1
