"""#20 — check_liveness_open: verify liveness under the SAME EnvironmentSpec faults as check_open,
without hand-rolling the faults as unfair actions a second time."""

from __future__ import annotations

from dataclasses import dataclass

from musil import (
    Action,
    Assumption,
    EnvironmentSpec,
    Model,
    OpenLivenessResult,
    check_liveness_open,
    check_open,
)


@dataclass(frozen=True)
class N:
    n: int


def _system() -> Model[N]:
    # the system's own move: advance toward the goal n==2
    return Model(
        init=N(0),
        actions=[Action("advance", enabled=lambda s: s.n < 2, apply=lambda s: N(s.n + 1))],
        invariants={"bounded": lambda s: s.n <= 2},
        terminal=lambda s: s.n == 2,  # the goal is a legit sink, not a deadlock
    )


def _stall_env() -> EnvironmentSpec[N]:
    # adversary: at n==1 it can self-loop forever (stall progress). Unfair by default.
    return EnvironmentSpec(
        name="stall",
        behaviors=[Action("stall", enabled=lambda s: s.n == 1, apply=lambda s: N(1))],
        guarantees={"bounded": lambda s: s.n <= 2},
        assumptions={"sched": Assumption("sched", "the stall cannot persist forever", status="unverified")},
    )


def test_liveness_holds_under_default_fairness_system_moves_only():
    # default fair = the system's own moves ({advance}); weak fairness of advance breaks the stall loop
    r = check_liveness_open(_system(), _stall_env(), goal=lambda s: s.n == 2)
    assert isinstance(r, OpenLivenessResult)
    assert r.ok


def test_strict_no_fairness_finds_the_stall_cycle():
    # fair=() : the stall self-loop at n==1 is an admissible cycle that never reaches the goal
    r = check_liveness_open(_system(), _stall_env(), goal=lambda s: s.n == 2, fair=())
    assert not r.ok
    assert r.result.kind == "fair-cycle"


def test_unverified_assumptions_are_surfaced():
    r = check_liveness_open(_system(), _stall_env(), goal=lambda s: s.n == 2)
    assert [a.name for a in r.unverified_assumptions] == ["sched"]
    assert "sched" in str(r)


def test_same_env_feeds_check_open_for_safety():
    # the whole point: one EnvironmentSpec, consumed by both the safety and the liveness form
    env = _stall_env()
    assert check_open(_system(), env).ok  # safety: bounded holds under the fault
    assert check_liveness_open(_system(), env, goal=lambda s: s.n == 2).ok  # liveness: goal still reached


def test_no_env_matches_plain_check_liveness_with_system_fairness():
    r = check_liveness_open(_system(), goal=lambda s: s.n == 2)
    assert r.ok  # advance always reaches n==2
    assert r.unverified_assumptions == ()
