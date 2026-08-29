"""#18 — coverage() works on actions_fn models (was blind, reporting 0 actions)."""

from __future__ import annotations

from dataclasses import dataclass

from musil import Action, Model, coverage


@dataclass(frozen=True)
class C:
    n: int


def _menu_model() -> Model[C]:
    # actions_fn offers per-state, uniquely-named actions: noop{n} (self-loop, always) and inc{n} (n<2).
    def actions_fn(s: C) -> list[Action[C]]:
        acts: list[Action[C]] = [Action(f"noop{{{s.n}}}", enabled=lambda st: True, apply=lambda st: st)]
        if s.n < 2:
            acts.append(Action(f"inc{{{s.n}}}", enabled=lambda st: True, apply=lambda st: C(st.n + 1)))
        return acts

    return Model(init=C(0), actions_fn=actions_fn, terminal=lambda s: False)


def _kind(name: str) -> str:
    return name.split("{")[0]


def test_coverage_is_no_longer_blind_for_actions_fn_models():
    # Before the fix this reported actions_total == 0 ("all 0 actions fire and move").
    cov = coverage(_menu_model())
    assert cov.actions_total > 0  # universe now derived from actions_fn, not the empty static list
    assert cov.actions_total == 5  # the 5 distinct raw names across states 0,1,2


def test_coverage_key_buckets_actions_fn_names_into_kinds():
    cov = coverage(_menu_model(), key=_kind)
    assert cov.actions_total == 2  # "inc" and "noop"
    assert cov.dead_actions == ()  # both kinds fire
    assert cov.always_enabled_actions == ("noop",)  # noop offered+fired in every state; inc only where n<2
    assert cov.stutter_only_actions == ("noop",)  # noop only ever self-loops
    assert not cov.ok


def test_a_dead_kind_is_detected_because_actions_fn_offers_it():
    # "blocked" is OFFERED at every state but never enabled -> a dead kind, detectable because the
    # enumerator exposes it even though it leaves no edge.
    def actions_fn(s: C) -> list[Action[C]]:
        return [
            Action(f"inc{{{s.n}}}", enabled=lambda st: st.n < 2, apply=lambda st: C(st.n + 1)),
            Action(f"blocked{{{s.n}}}", enabled=lambda st: False, apply=lambda st: C(99)),
        ]

    m = Model(init=C(0), actions_fn=actions_fn, terminal=lambda s: s.n == 2)
    cov = coverage(m, key=_kind)
    assert "blocked" in cov.dead_actions
    assert "inc" not in cov.dead_actions


def test_static_action_models_are_unchanged():
    m = Model(
        init=C(0),
        actions=[
            Action("inc", enabled=lambda s: s.n < 2, apply=lambda s: C(s.n + 1)),
            Action("dead", enabled=lambda s: False, apply=lambda s: C(0)),
        ],
        terminal=lambda s: s.n == 2,
    )
    cov = coverage(m)
    assert cov.actions_total == 2
    assert cov.dead_actions == ("dead",)
