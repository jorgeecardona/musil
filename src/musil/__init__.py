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
- ``musil.refine`` / ``musil.conformance`` — refinement and code-conformance checking
- ``musil.fsm`` / ``musil.faults`` / ``musil.channels`` / ``musil.compose`` / ``musil.clock`` /
  ``musil.reconciler`` — model-building kits
- ``musil.patterns`` — named liveness sugar (``always``, ``eventually``, ``recurs``, ``responds``)
- ``musil.counterexample`` / ``musil.diffing`` / ``musil.cache`` / ``musil.profiling`` /
  ``musil.doctor`` / ``musil.citations`` / ``musil.graph`` / ``musil.history`` / ``musil.tracing``

See ``docs/migrating.md`` for the import-path changes from the pre-0.35 flat namespace.
"""

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
