"""DOT export of the reachable state graph."""

from __future__ import annotations

from dataclasses import dataclass

from musil import Action, Model, check
from musil.graph import to_dot


@dataclass(frozen=True)
class Light:
    color: str = "red"


def _light() -> Model[Light]:
    return Model(
        init=Light("red"),
        actions=[
            Action("go", lambda s: s.color == "red", lambda _s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda _s: Light("yellow")),
            Action("stop", lambda s: s.color == "yellow", lambda _s: Light("red")),
        ],
    )


def test_dot_has_nodes_edges_and_marks_init() -> None:
    dot = to_dot(_light())
    assert dot.startswith("digraph musil {")
    assert dot.rstrip().endswith("}")
    # a node label per state, and an edge label per action
    for color in ("red", "green", "yellow"):
        assert f"color={color}" in dot
    for action in ("go", "slow", "stop"):
        assert f'label="{action}"' in dot
    assert "penwidth=2" in dot  # the initial state is drawn bold


def test_highlight_colors_the_trace_path() -> None:
    # an invariant that fails at yellow, then highlight the counterexample states
    model = Model(
        init=Light("red"),
        actions=_light().actions,
        invariants={"never-yellow": lambda s: s.color != "yellow"},
    )
    result = check(model)
    assert not result.ok
    dot = to_dot(model, highlight=[step.state for step in result.trace])
    assert 'color="red"' in dot  # at least one highlighted edge
    assert "fillcolor=" in dot
