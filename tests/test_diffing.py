"""``diff`` — the behavioral delta between two model versions."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace

from musil import Action, Invariant, Model
from musil.diffing import ModelDiff, diff


@dataclass(frozen=True)
class C:
    n: int


def _model(cap: int, small: int) -> Model[C]:
    inv: dict[str, Invariant[C]] = {"small": lambda s: s.n <= small}
    return Model(
        init=C(0),
        actions=[Action("inc", enabled=lambda s: s.n < cap, apply=lambda s: dc_replace(s, n=s.n + 1))],
        invariants=inv,
        terminal=lambda s: s.n == cap,
    )


def test_identical_models_are_equivalent():
    d = diff(_model(cap=3, small=1), _model(cap=3, small=1))
    assert isinstance(d, ModelDiff)
    assert d.equivalent
    assert str(d).startswith("MODELS EQUIVALENT")


def test_reports_new_states_and_transitions():
    d = diff(_model(cap=3, small=1), _model(cap=4, small=1))
    assert d.states_only_in_a == ()
    assert d.states_only_in_b == (C(4),)
    assert (C(3), "inc", C(4)) in d.transitions_only_in_b
    assert d.transitions_only_in_a == ()
    assert not d.equivalent


def test_reports_invariant_outcome_changes_on_shared_states():
    # Same reachable space (cap=3), but the "small" invariant differs: n<=1 vs n<=2.
    d = diff(_model(cap=3, small=1), _model(cap=3, small=2))
    assert d.states_only_in_a == () and d.states_only_in_b == ()
    # only n=2 flips: A says 2<=1 is False, B says 2<=2 is True
    assert d.invariant_changes == ((C(2), "small", False, True),)
    assert not d.equivalent


def test_str_summarizes_a_nonempty_diff():
    s = str(diff(_model(cap=3, small=1), _model(cap=4, small=2)))
    assert s.startswith("MODEL DIFF:")
    assert "only in B" in s
    assert "invariant-outcome change" in s
