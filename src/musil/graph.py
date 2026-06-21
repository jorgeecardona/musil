"""Render a model's reachable state graph as Graphviz DOT — the same artifact FizzBee emits, but
from the Python model. ``to_dot(model)`` explores the model and returns a DOT string you can pipe to
``dot -Tsvg``. Pass ``highlight`` (a sequence of states, e.g. the states of a counterexample trace)
to colour that path — handy for visualising why a check failed."""

from __future__ import annotations

from collections.abc import Hashable, Iterable

from musil.core import Graph, Model, explore


def _label(state: object) -> str:
    """A compact one-line label: ``field=value, ...`` for a dataclass state, else ``str(state)``."""
    fields = getattr(state, "__dataclass_fields__", None)
    if fields:
        return ", ".join(f"{f}={getattr(state, f)}" for f in fields)
    return str(state)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def to_dot[S: Hashable](
    source: Model[S] | Graph[S],
    *,
    highlight: Iterable[S] = (),
    name: str = "musil",
    max_states: int = 1_000_000,
) -> str:
    """Graphviz DOT for the reachable state graph. ``source`` is a Model (explored here) or a
    pre-built Graph. Initial states are drawn bold; ``highlight`` states are filled and edges between
    two highlighted states are red (e.g. ``highlight=[s.state for s in result.trace]``)."""
    graph = source if isinstance(source, Graph) else explore(source, max_states=max_states)
    idx = {s: i for i, s in enumerate(graph.states)}
    hi = set(highlight)
    inits = set(graph.initial)

    lines = [
        f"digraph {name} {{",
        "  rankdir=LR;",
        '  node [shape=box, fontname="monospace"];',
        '  edge [fontname="monospace"];',
    ]
    for s in graph.states:
        attrs = [f'label="{_escape(_label(s))}"']
        if s in inits:
            attrs.append("penwidth=2")
        if s in hi:
            attrs += ["style=filled", 'fillcolor="#ffe0e0"']
        lines.append(f"  n{idx[s]} [{', '.join(attrs)}];")
    for s in graph.states:
        for action, t in graph.edges[s]:
            edge_attrs = [f'label="{_escape(action)}"']
            if s in hi and t in hi:
                edge_attrs.append('color="red"')
                edge_attrs.append("penwidth=2")
            lines.append(f"  n{idx[s]} -> n{idx[t]} [{', '.join(edge_attrs)}];")
    lines.append("}")
    return "\n".join(lines) + "\n"
