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

from musil.channels import channel_actions, fifo_channel_actions, fifo_send, send
from musil.compose import Composite, compose
from musil.conformance import ConformanceResult, Divergence, generate_traces, replay
from musil.core import (
    Action,
    Graph,
    Invariant,
    Model,
    Result,
    StateViolation,
    Step,
    check,
    explore,
    format_trace,
    invariant_from_violations,
    reachable_violations,
    symmetry_reduction_sound,
)
from musil.env import Assumption, EnvironmentSpec, OpenResult, check_open
from musil.fsm import (
    declared_states,
    multi_status_field_actions,
    status_field_actions,
    terminal_states,
    transition_actions,
)
from musil.graph import to_dot
from musil.liveness import LivenessResult, check_liveness
from musil.metrics import (
    StateSpaceMetrics,
    metrics_of,
    solution_cardinality,
    state_space_metrics,
)
from musil.refine import (
    RefinementMonitor,
    RefinementResult,
    RefinementViolation,
    check_refinement,
)
from musil.sim import (
    AdversarialNode,
    BaseNode,
    Context,
    Crash,
    Envelope,
    FaultSchedule,
    NetworkModel,
    Node,
    Partition,
    RunResult,
    SimFailure,
    SimReport,
    Simulator,
    simulate,
)

__all__ = [
    "Action",
    "AdversarialNode",
    "Assumption",
    "BaseNode",
    "Composite",
    "ConformanceResult",
    "Context",
    "Crash",
    "Divergence",
    "Envelope",
    "EnvironmentSpec",
    "FaultSchedule",
    "Graph",
    "Invariant",
    "LivenessResult",
    "Model",
    "NetworkModel",
    "Node",
    "OpenResult",
    "Partition",
    "RefinementMonitor",
    "RefinementResult",
    "RefinementViolation",
    "Result",
    "RunResult",
    "SimFailure",
    "SimReport",
    "Simulator",
    "StateSpaceMetrics",
    "StateViolation",
    "Step",
    "channel_actions",
    "check",
    "check_liveness",
    "check_open",
    "check_refinement",
    "compose",
    "declared_states",
    "explore",
    "fifo_channel_actions",
    "fifo_send",
    "format_trace",
    "generate_traces",
    "invariant_from_violations",
    "metrics_of",
    "multi_status_field_actions",
    "reachable_violations",
    "replay",
    "send",
    "simulate",
    "solution_cardinality",
    "state_space_metrics",
    "status_field_actions",
    "symmetry_reduction_sound",
    "terminal_states",
    "to_dot",
    "transition_actions",
]
