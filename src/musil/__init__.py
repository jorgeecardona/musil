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

from musil.cache import check_cached, clear_verdict_cache
from musil.channels import channel_actions, fifo_channel_actions, fifo_send, send
from musil.clock import BoundedClock, bounded_clock
from musil.compose import Composite, compose
from musil.conformance import (
    ConformanceResult,
    Divergence,
    areplay,
    generate_traces,
    replay,
)
from musil.core import (
    Action,
    ActionSchema,
    FixedPoints,
    Graph,
    Invariant,
    Model,
    Result,
    StateViolation,
    Step,
    Verdict,
    assert_ok,
    check,
    check_all,
    enumerate_actions,
    explore,
    fixed_points,
    footprint_sound,
    format_trace,
    format_trace_diff,
    invariant_from_violations,
    reachable_violations,
    reaches,
    symmetry_reduction_sound,
)
from musil.env import Assumption, EnvironmentSpec, OpenResult, check_open
from musil.fsm import (
    declared_states,
    multi_status_field_actions,
    protocol_actions,
    protocol_operations,
    status_field_actions,
    terminal_states,
    transition_actions,
)
from musil.graph import to_dot
from musil.liveness import LivenessResult, check_liveness
from musil.metrics import (
    Coverage,
    InvariantCoverage,
    StateSpaceMetrics,
    coverage,
    coverage_of,
    invariant_coverage,
    invariant_coverage_of,
    metrics_of,
    solution_cardinality,
    state_space_metrics,
)
from musil.profiling import ActionCost, Phase, Profile, profile
from musil.refine import (
    RefinementMonitor,
    RefinementResult,
    RefinementViolation,
    acheck_refinement,
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
from musil.symmetry import canonical_by_fields, canonical_by_permutations, canonical_by_sorting

__all__ = [
    "Action",
    "ActionCost",
    "ActionSchema",
    "AdversarialNode",
    "Assumption",
    "BaseNode",
    "BoundedClock",
    "Composite",
    "ConformanceResult",
    "Context",
    "Coverage",
    "Crash",
    "Divergence",
    "Envelope",
    "EnvironmentSpec",
    "FaultSchedule",
    "FixedPoints",
    "Graph",
    "Invariant",
    "InvariantCoverage",
    "LivenessResult",
    "Model",
    "NetworkModel",
    "Node",
    "OpenResult",
    "Partition",
    "Phase",
    "Profile",
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
    "Verdict",
    "acheck_refinement",
    "areplay",
    "assert_ok",
    "bounded_clock",
    "canonical_by_fields",
    "canonical_by_permutations",
    "canonical_by_sorting",
    "channel_actions",
    "check",
    "check_all",
    "check_cached",
    "check_liveness",
    "check_open",
    "check_refinement",
    "clear_verdict_cache",
    "compose",
    "coverage",
    "coverage_of",
    "declared_states",
    "enumerate_actions",
    "explore",
    "fifo_channel_actions",
    "fifo_send",
    "fixed_points",
    "footprint_sound",
    "format_trace",
    "format_trace_diff",
    "generate_traces",
    "invariant_coverage",
    "invariant_coverage_of",
    "invariant_from_violations",
    "metrics_of",
    "multi_status_field_actions",
    "profile",
    "protocol_actions",
    "protocol_operations",
    "reachable_violations",
    "reaches",
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
