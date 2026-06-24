"""Open-system verification: EnvironmentSpec, check_open, Assumption."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Assumption, EnvironmentSpec, Model, check, check_open


@dataclass(frozen=True)
class Service:
    """A simple service that can be in one of three states."""

    status: str        # "idle", "running", "crashed"
    result: int | None = None


def _base_model() -> Model[Service]:
    return Model(
        init=Service("idle"),
        actions=[
            Action("start", lambda s: s.status == "idle", lambda s: replace(s, status="running")),
            Action("compute", lambda s: s.status == "running", lambda s: replace(s, status="running", result=42)),
            Action("stop", lambda s: s.status == "running", lambda s: replace(s, status="idle", result=None)),
        ],
        invariants={
            "valid-status": lambda s: s.status in {"idle", "running", "crashed"},
        },
    )


# --- check_open with no environments is identical to check ---

def test_check_open_no_envs_matches_check() -> None:
    model = _base_model()
    r_closed = check(model)
    r_open = check_open(model)
    assert r_closed.ok == r_open.result.ok
    assert r_closed.states_explored == r_open.result.states_explored
    assert r_open.unverified_assumptions == ()


# --- environment behaviors are explored (adversarial crash catches invariant violation) ---

def test_env_crash_behavior_is_explored() -> None:
    model = _base_model()

    crash_env = EnvironmentSpec[Service](
        name="platform",
        behaviors=[
            Action("env:crash", lambda s: s.status == "running", lambda s: replace(s, status="bad")),
        ],
    )

    result = check_open(model, crash_env)
    assert not result.ok
    assert result.result.kind == "invariant"
    assert result.result.invariant == "valid-status"


# --- env behavior is explored but system handles it gracefully ---

def test_system_tolerates_env_crash_when_invariant_permits() -> None:
    # "crashed" is a valid terminal sink — the system doesn't need to recover from it.
    model = Model(
        init=Service("idle"),
        actions=[
            Action("start", lambda s: s.status == "idle", lambda s: replace(s, status="running")),
            Action("stop", lambda s: s.status == "running", lambda s: replace(s, status="idle")),
        ],
        invariants={
            "valid-status": lambda s: s.status in {"idle", "running", "crashed"},
        },
        terminal=lambda s: s.status == "crashed",
    )

    crash_env = EnvironmentSpec[Service](
        name="platform",
        behaviors=[
            Action("env:crash", lambda s: s.status == "running", lambda s: replace(s, status="crashed")),
        ],
    )

    result = check_open(model, crash_env)
    assert result.ok, str(result)


# --- env guarantee violation is reported with qualified name ---

def test_env_guarantee_violation_reported() -> None:
    model = _base_model()

    env_with_broken_guarantee = EnvironmentSpec[Service](
        name="scheduler",
        behaviors=[
            Action("env:reschedule", lambda s: s.status == "running", lambda s: replace(s, status="running", result=-1)),
        ],
        guarantees={
            "result-non-negative": lambda s: s.result is None or s.result >= 0,
        },
    )

    result = check_open(model, env_with_broken_guarantee)
    assert not result.ok
    assert result.result.invariant == "scheduler:result-non-negative"


# --- unverified assumptions are surfaced ---

def test_unverified_assumptions_collected() -> None:
    model = _base_model()

    env = EnvironmentSpec[Service](
        name="aws",
        behaviors=[],
        assumptions={
            "s3-eventual-delivery": Assumption(
                name="s3-eventual-delivery",
                description="S3 PUT responses eventually arrive",
                status="unverified",
                source="AWS SLA",
            ),
            "iam-correctness": Assumption(
                name="iam-correctness",
                description="IAM correctly enforces permissions",
                status="verified",
                source="AWS docs",
            ),
        },
    )

    result = check_open(model, env)
    assert result.ok
    unverified_names = {a.name for a in result.unverified_assumptions}
    assert "s3-eventual-delivery" in unverified_names
    assert "iam-correctness" not in unverified_names


# --- axiom assumptions are also surfaced (they are not "verified") ---

def test_axiom_assumptions_surfaced() -> None:
    model = _base_model()
    env = EnvironmentSpec[Service](
        name="hardware",
        behaviors=[],
        assumptions={
            "memory-safe": Assumption(
                name="memory-safe",
                description="Physical memory does not corrupt silently",
                status="axiom",
            ),
        },
    )

    result = check_open(model, env)
    assert result.ok
    axioms = [a for a in result.unverified_assumptions if a.status == "axiom"]
    assert len(axioms) == 1
    assert axioms[0].name == "memory-safe"


# --- multiple environments compose correctly ---

def test_multiple_envs_compose() -> None:
    model = _base_model()

    env_a = EnvironmentSpec[Service](
        name="k8s",
        behaviors=[
            Action("k8s:evict", lambda s: s.status == "running", lambda s: replace(s, status="idle", result=None)),
        ],
    )
    env_b = EnvironmentSpec[Service](
        name="linux",
        behaviors=[
            Action("linux:oom", lambda s: s.status == "running", lambda s: replace(s, status="idle", result=None)),
        ],
    )

    result = check_open(model, env_a, env_b)
    # both evict and oom lead to "idle", which is valid -- system tolerates both
    assert result.ok, str(result)


# --- OpenResult bool and str ---

def test_open_result_bool_delegates_to_result() -> None:
    model = _base_model()
    good = check_open(model)
    assert bool(good) is True
    assert "OK" in str(good)

    bad_env = EnvironmentSpec[Service](
        name="bad",
        behaviors=[Action("bad:corrupt", lambda _s: True, lambda s: replace(s, status="unknown"))],
    )
    bad = check_open(model, bad_env)
    assert bool(bad) is False


# --- Assumption.predicate (optional machine-checkable form) ---

def test_assumption_with_predicate() -> None:
    a = Assumption(
        name="always-idle-or-running",
        description="Status is never 'crashed'",
        status="unverified",
        predicate=lambda s: s.status != "crashed",  # type: ignore[arg-type]
    )
    assert a.predicate is not None
    assert a.predicate(Service("idle"))
    assert not a.predicate(Service("crashed"))
