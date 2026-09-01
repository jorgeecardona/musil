"""``musil.patterns`` — the global-scope Dwyer patterns as one-call helpers."""

from __future__ import annotations

from dataclasses import dataclass

from musil import Action, Model
from musil.patterns import absent, always, eventually, recurs, responds


@dataclass(frozen=True)
class Light:
    color: str


def _light() -> Model[Light]:
    # cycles forever: red -> green -> yellow -> red
    return Model(
        init=Light("red"),
        actions=[
            Action("go", enabled=lambda s: s.color == "red", apply=lambda s: Light("green")),
            Action("slow", enabled=lambda s: s.color == "green", apply=lambda s: Light("yellow")),
            Action("stop", enabled=lambda s: s.color == "yellow", apply=lambda s: Light("red")),
        ],
    )


def test_always_universality():
    m = _light()
    assert always(m, lambda s: s.color in {"red", "green", "yellow"}).ok
    bad = always(m, lambda s: s.color != "yellow")  # yellow is reachable
    assert not bad.ok
    assert bad.kind == "invariant"


def test_absent():
    m = _light()
    assert absent(m, lambda s: s.color == "blue").ok  # blue never occurs
    assert not absent(m, lambda s: s.color == "green").ok  # green is reachable


def test_eventually_existence():
    m = _light()
    assert eventually(m, lambda s: s.color == "green").ok  # every run reaches green


def test_recurs_recurrence():
    m = _light()
    assert recurs(m, lambda s: s.color == "red").ok  # red recurs infinitely often around the cycle


def test_responds_leads_to():
    m = _light()
    # whenever yellow, red eventually follows
    assert responds(m, trigger=lambda s: s.color == "yellow", response=lambda s: s.color == "red").ok


def test_responds_fails_when_response_can_be_starved():
    # a light that can get stuck on green: from green, either slow (->yellow) or stall (->green forever)
    m = Model(
        init=Light("red"),
        actions=[
            Action("go", enabled=lambda s: s.color == "red", apply=lambda s: Light("green")),
            Action("slow", enabled=lambda s: s.color == "green", apply=lambda s: Light("yellow")),
            Action("stall", enabled=lambda s: s.color == "green", apply=lambda s: Light("green")),
            Action("stop", enabled=lambda s: s.color == "yellow", apply=lambda s: Light("red")),
        ],
    )
    # green may loop on 'stall' forever, so "green responds-to yellow" style eventually-red can be starved
    r = responds(m, trigger=lambda s: s.color == "green", response=lambda s: s.color == "red")
    assert not r.ok  # the stall self-loop is a fair-cycle counterexample under no fairness
