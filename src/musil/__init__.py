"""musil — a tiny, dependency-free explicit-state model checker.

Named for Robert Musil, the engineer-mathematician turned novelist.

Define states as immutable values (a frozen dataclass), actions as guarded pure transitions, and
invariants as predicates; ``check`` sweeps every reachable state (and every interleaving of
concurrent actors) for the first invariant violation or deadlock, with the shortest trace.

    from dataclasses import dataclass
    from musil import Action, Model, check

    @dataclass(frozen=True)
    class Light:
        color: str

    model = Model(
        init=Light("red"),
        actions=[
            Action("go",   lambda s: s.color == "red",   lambda s: Light("green")),
            Action("slow", lambda s: s.color == "green", lambda s: Light("yellow")),
            Action("stop", lambda s: s.color == "yellow", lambda s: Light("red")),
        ],
        invariants={"known-color": lambda s: s.color in {"red", "green", "yellow"}},
    )
    assert check(model).ok
"""

from musil.channels import channel_actions, send
from musil.compose import Composite, compose
from musil.conformance import ConformanceResult, Divergence, generate_traces, replay
from musil.core import (
    Action,
    Graph,
    Invariant,
    Model,
    Result,
    Step,
    check,
    explore,
    format_trace,
)
from musil.fsm import (
    declared_states,
    status_field_actions,
    terminal_states,
    transition_actions,
)
from musil.graph import to_dot
from musil.liveness import LivenessResult, check_liveness

__all__ = [
    "Action",
    "Composite",
    "ConformanceResult",
    "Divergence",
    "Graph",
    "Invariant",
    "LivenessResult",
    "Model",
    "Result",
    "Step",
    "channel_actions",
    "check",
    "check_liveness",
    "compose",
    "declared_states",
    "explore",
    "format_trace",
    "generate_traces",
    "replay",
    "send",
    "status_field_actions",
    "terminal_states",
    "to_dot",
    "transition_actions",
]
