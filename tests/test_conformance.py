"""Conformance: generate traces from a model, replay against a (real-ish) implementation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, generate_traces, replay


@dataclass(frozen=True)
class Light:
    color: str = "red"


MODEL = Model(
    init=Light("red"),
    actions=[
        Action("go", lambda s: s.color == "red", lambda s: replace(s, color="green")),
        Action("slow", lambda s: s.color == "green", lambda s: replace(s, color="yellow")),
        Action("stop", lambda s: s.color == "yellow", lambda s: replace(s, color="red")),
    ],
)

# the "real implementation": a plain string-state machine, independent of the model dataclass
_NEXT = {"go": ("red", "green"), "slow": ("green", "yellow"), "stop": ("yellow", "red")}


def _correct_step(color: str, action: str) -> str:
    src, dst = _NEXT[action]
    return dst if color == src else color


def _buggy_step(color: str, action: str) -> str:
    if action == "go" and color == "red":
        return "yellow"  # BUG: red --go--> yellow instead of green
    return _correct_step(color, action)


def test_edge_traces_cover_every_transition() -> None:
    traces = generate_traces(MODEL, cover="edges")
    # one trace per reachable edge; the light has 3 edges
    assert len(traces) == 3
    assert all(t[0].action == "<init>" for t in traces)


def test_correct_implementation_conforms() -> None:
    traces = generate_traces(MODEL, cover="edges")
    result = replay(
        traces,
        step_fn=_correct_step,
        project=lambda color: Light(color),
        start="red",
    )
    assert result.ok, str(result)
    assert result.steps_run > 0


def test_buggy_implementation_is_caught() -> None:
    traces = generate_traces(MODEL, cover="edges")
    result = replay(
        traces,
        step_fn=_buggy_step,
        project=lambda color: Light(color),
        start="red",
    )
    assert not result.ok
    d = result.divergence
    assert d is not None
    assert d.action == "go"
    assert d.expected == Light("green") and d.actual == Light("yellow")


def test_projection_mismatch_at_init_is_caught() -> None:
    traces = generate_traces(MODEL, cover="states")
    result = replay(
        traces, step_fn=_correct_step, project=lambda color: Light(color), start="green"
    )
    assert not result.ok
    assert result.divergence is not None and result.divergence.step_index == 0
