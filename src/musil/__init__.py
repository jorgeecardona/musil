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

The top level exports the CORE checking API — modelling (``Model``, ``Action``), the checks
(``check``, ``check_all``, ``explore``, ``check_liveness``, ``check_ltl``), results and traces
(``Result``, ``Step``, ``format_trace``, ``witness`` …), the LTL formula AST, and the test
assertions. Everything else lives in a submodule, imported directly:

- ``musil.probabilistic`` — exact DTMC / MDP probabilities (reachability, reward, steady-state, PLTL)
- ``musil.sim`` — sampling-based simulation of faulty distributed runs
- ``musil.env`` — open-system checking against adversarial environments (``check_open``)
- ``musil.metrics`` — coverage and vacuity (is a green check meaningful?)
- ``musil.induction`` — ``check_inductive`` (proof by k-induction, unbounded depth)
- ``musil.symmetry`` / ``musil.por`` — symmetry and partial-order reduction, with soundness gates
- ``musil.parallel`` — ``parallel_check``: the BFS fanned across fork processes (``check(workers=N)``)
- ``musil.refine`` / ``musil.conformance`` — refinement and code-conformance checking
- ``musil.fsm`` / ``musil.petri`` / ``musil.faults`` / ``musil.channels`` / ``musil.compose`` /
  ``musil.clock`` / ``musil.reconciler`` — model-building kits
- ``musil.patterns`` — named liveness sugar (``always``, ``eventually``, ``recurs``, ``responds``)
- ``musil.counterexample`` / ``musil.diffing`` / ``musil.cache`` / ``musil.profiling`` /
  ``musil.doctor`` / ``musil.citations`` / ``musil.graph`` / ``musil.history`` / ``musil.tracing``

See ``docs/migrating.md`` for the import-path changes from the pre-0.35 flat namespace.
"""

import importlib
import warnings

from musil.core import (
    Action,
    EdgeInvariant,
    Graph,
    Invariant,
    Model,
    Result,
    Step,
    Verdict,
    assert_ok,
    assert_violates,
    check,
    check_all,
    check_of,
    explore,
    format_trace,
    path_to,
    reaches,
    states_where,
    witness,
)
from musil.liveness import LivenessResult, check_liveness
from musil.ltl import (
    LTL,
    Always,
    And,
    Atom,
    Eventually,
    Implies,
    Next,
    Not,
    Or,
    Release,
    Until,
    WeakUntil,
    check_ltl,
)

__version__ = "0.36.10"  # the single source of truth; pyproject reads it via [tool.hatch.version]

__all__ = [
    "LTL",
    "Action",
    "Always",
    "And",
    "Atom",
    "EdgeInvariant",
    "Eventually",
    "Graph",
    "Implies",
    "Invariant",
    "LivenessResult",
    "Model",
    "Next",
    "Not",
    "Or",
    "Release",
    "Result",
    "Step",
    "Until",
    "Verdict",
    "WeakUntil",
    "assert_ok",
    "assert_violates",
    "check",
    "check_all",
    "check_liveness",
    "check_ltl",
    "check_of",
    "explore",
    "format_trace",
    "path_to",
    "reaches",
    "states_where",
    "witness",
]

# Backward-compat shim (deprecated). The pre-0.35 flat API re-exported every name from the top level;
# these now live in submodules. Importing one from ``musil`` still works but warns and will be removed
# in a future release — import from the submodule named here instead. See ``docs/migrating.md``.
_MOVED = {
    "ActionCost": "profiling",
    "ActionSchema": "core",
    "AdversarialNode": "sim",
    "Assumption": "env",
    "BaseNode": "sim",
    "BoundedClock": "clock",
    "Buchi": "ltl",
    "Checkpoint": "conformance",
    "Citation": "citations",
    "Composite": "compose",
    "ConformanceResult": "conformance",
    "Context": "sim",
    "Convergence": "conformance",
    "ConvergenceMonitor": "conformance",
    "Coverage": "metrics",
    "Crash": "sim",
    "Divergence": "conformance",
    "Envelope": "sim",
    "EnvironmentSpec": "env",
    "FaultDrive": "sim",
    "FaultSchedule": "sim",
    "Finding": "doctor",
    "FixedPoints": "core",
    "GeneralizedBuchi": "ltl",
    "InductionResult": "induction",
    "InvariantCoverage": "metrics",
    "LastAction": "history",
    "ModelDiff": "diffing",
    "NetworkModel": "sim",
    "Node": "sim",
    "OpenLivenessResult": "env",
    "OpenResult": "env",
    "Partition": "sim",
    "PetriNet": "petri",
    "Phase": "profiling",
    "PortfolioCoverage": "metrics",
    "Profile": "profiling",
    "RefinementMonitor": "refine",
    "RefinementResult": "refine",
    "RefinementViolation": "refine",
    "RunResult": "sim",
    "ScenarioResult": "conformance",
    "SimFailure": "sim",
    "SimReport": "sim",
    "Simulator": "sim",
    "StateSpaceMetrics": "metrics",
    "StateViolation": "core",
    "absent": "patterns",
    "acheck_refinement": "refine",
    "action_taken": "history",
    "always": "patterns",
    "areplay": "conformance",
    "as_regression_test": "counterexample",
    "assert_converged": "conformance",
    "assert_covers": "metrics",
    "assert_covers_table": "fsm",
    "assert_place_invariant": "petri",
    "assert_probability": "probabilistic",
    "assert_scenarios": "conformance",
    "bounded_clock": "clock",
    "canonical_by_fields": "symmetry",
    "canonical_by_permutations": "symmetry",
    "canonical_by_sorting": "symmetry",
    "channel_actions": "channels",
    "check_cached": "cache",
    "check_inductive": "induction",
    "check_liveness_of": "liveness",
    "check_liveness_open": "env",
    "check_open": "env",
    "check_refinement": "refine",
    "clear_verdict_cache": "cache",
    "compose": "compose",
    "coverage": "metrics",
    "coverage_of": "metrics",
    "crash_actions": "faults",
    "dangling_citations": "citations",
    "declared_accounts": "fsm",
    "declared_states": "fsm",
    "diff": "diffing",
    "drive_scenarios": "conformance",
    "endpoints_of": "fsm",
    "enumerate_actions": "core",
    "eventually": "patterns",
    "expected_reward": "probabilistic",
    "expected_reward_mdp": "probabilistic",
    "explore_por": "por",
    "fifo_channel_actions": "channels",
    "fifo_send": "channels",
    "find_citations": "citations",
    "fixed_points": "core",
    "fixed_points_of": "core",
    "footprint_sound": "core",
    "format_trace_diff": "core",
    "generate_traces": "conformance",
    "independent": "por",
    "invariant_coverage": "metrics",
    "invariant_coverage_of": "metrics",
    "invariant_from_violations": "core",
    "known_models": "citations",
    "long_run_probability": "probabilistic",
    "long_run_probability_mdp": "probabilistic",
    "long_run_reward": "probabilistic",
    "long_run_reward_mdp": "probabilistic",
    "metrics_of": "metrics",
    "minimize": "counterexample",
    "multi_status_field_actions": "fsm",
    "never": "core",
    "no_trace": "tracing",
    "parallel_check": "parallel",
    "partition_actions": "faults",
    "petri_actions": "petri",
    "petri_enabled": "petri",
    "petri_terminal": "petri",
    "place_invariants": "petri",
    "por_sound": "por",
    "portfolio_coverage": "metrics",
    "probability_ltl": "probabilistic",
    "profile": "profiling",
    "protocol_actions": "fsm",
    "protocol_operations": "fsm",
    "reach_probability": "probabilistic",
    "reach_probability_mdp": "probabilistic",
    "reachable_violations": "core",
    "reconciler": "reconciler",
    "recurs": "patterns",
    "replay": "conformance",
    "replay_actions": "counterexample",
    "replicated_transition_actions": "fsm",
    "responds": "patterns",
    "scan": "doctor",
    "send": "channels",
    "simulate": "sim",
    "solution_cardinality": "metrics",
    "state_space_metrics": "metrics",
    "status_field_actions": "fsm",
    "symmetry_reduction_sound": "core",
    "terminal_states": "fsm",
    "to_dot": "graph",
    "transient_distribution": "probabilistic",
    "transition_actions": "fsm",
    "with_last_action": "history",
}


def __getattr__(name: str) -> object:
    module = _MOVED.get(name)
    if module is not None:
        warnings.warn(
            f"'from musil import {name}' is deprecated since 0.35 — import it from 'musil.{module}' "
            f"instead (e.g. 'from musil.{module} import {name}'). This shim is removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(importlib.import_module(f"musil.{module}"), name)
    raise AttributeError(f"module 'musil' has no attribute {name!r}")
