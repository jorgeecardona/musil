"""#21 — distributed storage/state fault environments: credential_rotation and
record_reality_divergence."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, EnvironmentSpec, Model, check_open
from musil.environments.distributed import credential_rotation, record_reality_divergence


@dataclass(frozen=True)
class V:
    record: int  # what the component believes is attached / cached
    reality: int  # what is actually there
    used: bool


def _divergence_env() -> EnvironmentSpec[V]:
    return record_reality_divergence(
        can_diverge=lambda s: s.record == s.reality and not s.used,
        on_diverge=lambda s: dc_replace(s, reality=s.reality + 1),  # reality drifts; record goes stale
    )


def test_record_reality_divergence_catches_a_system_that_trusts_its_record():
    # "use" acts without re-validating record == reality, so the env exposes the bug.
    system = Model(
        init=V(1, 1, False),
        actions=[Action("use", enabled=lambda s: not s.used, apply=lambda s: dc_replace(s, used=True))],
        invariants={"no-use-on-divergence": lambda s: (not s.used) or s.record == s.reality},
        terminal=lambda s: s.used,
    )
    r = check_open(system, _divergence_env())
    assert not r.ok
    assert r.result.invariant == "no-use-on-divergence"
    # the assumption is surfaced as a residual obligation
    assert any(a.name == "distributed:reality-eventually-sensed" for a in r.unverified_assumptions)


def test_record_reality_divergence_passes_a_system_that_revalidates():
    # a correct system re-validates: "use" is enabled only when record == reality (senses reality first).
    system = Model(
        init=V(1, 1, False),
        actions=[
            Action("use", enabled=lambda s: not s.used and s.record == s.reality, apply=lambda s: dc_replace(s, used=True)),
            Action("resync", enabled=lambda s: s.record != s.reality, apply=lambda s: dc_replace(s, record=s.reality)),
        ],
        invariants={"no-use-on-divergence": lambda s: (not s.used) or s.record == s.reality},
        terminal=lambda s: s.used,
    )
    r = check_open(system, _divergence_env())
    assert r.ok  # re-validation defeats the fault


@dataclass(frozen=True)
class Cr:
    creds_valid: bool
    worked: bool
    bad: bool  # set iff an action ran while creds were invalid (an unauthenticated act)


def _rotation_env() -> EnvironmentSpec[Cr]:
    return credential_rotation(
        can_rotate=lambda s: s.creds_valid,
        on_rotate=lambda s: dc_replace(s, creds_valid=False),
    )


def test_credential_rotation_passes_a_system_that_guards_on_creds_and_surfaces_its_assumption():
    # 'act' is guarded on creds_valid, so a rotation only ever DISABLES it — never an unauthenticated act.
    system = Model(
        init=Cr(True, False, False),
        actions=[Action("act", enabled=lambda s: s.creds_valid and not s.worked, apply=lambda s: dc_replace(s, worked=True))],
        invariants={"no-unauthenticated-act": lambda s: not s.bad},
        terminal=lambda s: s.worked or not s.creds_valid,
    )
    r = check_open(system, _rotation_env())
    assert r.ok
    assert any(a.name == "distributed:credential-rotation-observed" for a in r.unverified_assumptions)


def test_credential_rotation_catches_an_unguarded_action():
    # buggy 'act' ignores creds_valid: a rotation before it acts records an unauthenticated act (bad=True).
    system = Model(
        init=Cr(True, False, False),
        actions=[
            Action(
                "act",
                enabled=lambda s: not s.worked,
                apply=lambda s: dc_replace(s, worked=True, bad=not s.creds_valid),
            )
        ],
        invariants={"no-unauthenticated-act": lambda s: not s.bad},
        terminal=lambda s: s.worked,
    )
    r = check_open(system, _rotation_env())
    assert not r.ok
    assert r.result.invariant == "no-unauthenticated-act"
