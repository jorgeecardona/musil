"""``profile`` — per-phase timing and hottest actions for a slow ``check``."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, Model, Profile, check, profile


@dataclass(frozen=True)
class C:
    n: int


def _model() -> Model[C]:
    return Model(
        init=C(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 5, apply=lambda s: dc_replace(s, n=s.n + 1)),
            Action("noop", enabled=lambda s: True, apply=lambda s: s),  # a self-loop: exercises apply
        ],
        invariants={"bound": lambda s: s.n <= 5},
        terminal=lambda s: s.n == 5,
    )


def test_profile_explores_the_same_states_as_check():
    m = _model()
    p = profile(m)
    assert isinstance(p, Profile)
    assert p.states_explored == 6  # n in 0..5
    assert p.states_explored == check(m).states_explored


def test_profile_records_all_phases():
    p = profile(_model())
    phase_names = {ph.name for ph in p.phases}
    assert {"invariants", "enumeration", "enablement", "apply", "canonicalize", "visited-set"} <= phase_names
    assert all(ph.calls > 0 for ph in p.phases)


def test_profile_records_and_sorts_actions_hottest_first():
    p = profile(_model())
    assert {a.name for a in p.actions} == {"inc", "noop"}
    assert all(a.enabled_calls > 0 for a in p.actions)
    totals = [a.total_seconds for a in p.actions]
    assert totals == sorted(totals, reverse=True)


def test_profile_str_is_a_readable_report():
    s = str(profile(_model()))
    assert s.startswith("PROFILE —")
    assert "by phase" in s
    assert "hottest actions" in s


def test_profile_states_per_second_is_nonnegative():
    assert profile(_model()).states_per_second >= 0.0
