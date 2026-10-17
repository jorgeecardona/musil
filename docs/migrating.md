# Migrating to the 0.35 API

**0.35 reorganises the public API.** The top-level `musil` package went from re-exporting all ~158 names to
exporting only the **core checking API** (~34 names). Every specialised layer now lives in its own submodule
and is imported directly. This makes the top level small enough to discover and teach, and makes the layering
explicit.

Nothing was renamed or removed — every function and class is exactly where it was defined. Only the *import
path* changed for the specialised names.

## What stays at the top level

```python
from musil import (
    Model, Action, Invariant, EdgeInvariant,          # modelling
    check, check_all, check_of, explore,              # the checks
    check_liveness, check_ltl,                        # temporal checks
    Result, Step, Verdict, Graph, LivenessResult,     # results
    format_trace, witness, path_to, reaches, states_where,   # traces / reachability
    assert_ok, assert_violates,                       # test assertions
    LTL, Atom, Not, And, Or, Implies,                 # LTL formula AST
    Next, Always, Eventually, Until, Release, WeakUntil,
)
```

If your code only used these, nothing changes.

## What moved to a submodule

Everything else is now `from musil.<module> import <name>`. Find the name in the table and prefix it with its
module:

| Import from | Names |
|---|---|
| `musil.probabilistic` | `reach_probability`, `reach_probability_mdp`, `expected_reward`, `expected_reward_mdp`, `long_run_probability`, `long_run_probability_mdp`, `long_run_reward`, `long_run_reward_mdp`, `probability_ltl`, `transient_distribution`, `assert_probability` |
| `musil.sim` | `simulate`, `Simulator`, `NetworkModel`, `Node`, `BaseNode`, `AdversarialNode`, `Context`, `Envelope`, `Crash`, `Partition`, `FaultSchedule`, `RunResult`, `SimReport`, `SimFailure` |
| `musil.env` | `check_open`, `check_liveness_open`, `EnvironmentSpec`, `Assumption`, `OpenResult`, `OpenLivenessResult` |
| `musil.metrics` | `coverage`, `coverage_of`, `invariant_coverage`, `invariant_coverage_of`, `portfolio_coverage`, `assert_covers`, `metrics_of`, `state_space_metrics`, `solution_cardinality`, `Coverage`, `InvariantCoverage`, `PortfolioCoverage`, `StateSpaceMetrics` |
| `musil.fsm` | `transition_actions`, `status_field_actions`, `multi_status_field_actions`, `protocol_actions`, `protocol_operations`, `replicated_transition_actions`, `movement_actions`, `declared_states`, `declared_accounts`, `endpoints_of`, `terminal_states`, `assert_covers_table` |
| `musil.refine` | `check_refinement`, `acheck_refinement`, `RefinementMonitor`, `RefinementResult`, `RefinementViolation` |
| `musil.conformance` | `replay`, `areplay`, `generate_traces`, `ConformanceResult`, `Divergence` |
| `musil.induction` | `check_inductive`, `InductionResult` |
| `musil.symmetry` | `canonical_by_sorting`, `canonical_by_fields`, `canonical_by_permutations` |
| `musil.por` | `explore_por`, `por_sound`, `independent` |
| `musil.faults` | `crash_actions`, `partition_actions` |
| `musil.channels` | `channel_actions`, `fifo_channel_actions`, `send`, `fifo_send` |
| `musil.compose` | `compose`, `Composite` |
| `musil.clock` | `bounded_clock`, `BoundedClock` |
| `musil.reconciler` | `reconciler` |
| `musil.patterns` | `always`, `eventually`, `recurs`, `responds`, `absent` |
| `musil.counterexample` | `minimize`, `replay_actions`, `as_regression_test` |
| `musil.diffing` | `diff`, `ModelDiff` |
| `musil.cache` | `check_cached`, `clear_verdict_cache` |
| `musil.profiling` | `profile`, `Profile`, `Phase`, `ActionCost` |
| `musil.doctor` | `scan`, `Finding` |
| `musil.citations` | `find_citations`, `dangling_citations`, `known_models`, `Citation` |
| `musil.graph` | `to_dot` |
| `musil.history` | `with_last_action`, `action_taken`, `LastAction` |
| `musil.tracing` | `no_trace` |
| `musil.core` (demoted from top level) | `reachable_violations`, `invariant_from_violations`, `fixed_points`, `fixed_points_of`, `footprint_sound`, `symmetry_reduction_sound`, `enumerate_actions`, `format_trace_diff`, `never`, `ActionSchema`, `StateViolation`, `FixedPoints` |
| `musil.ltl` (automata internals) | `Buchi`, `GeneralizedBuchi` |
| `musil.liveness` | `check_liveness_of` |

## Quick fix

Most codebases only need to move a handful of imports. If your editor flags an unresolved
`from musil import X`, look up `X` above and change it to `from musil.<module> import X`. A green
`pyright` / `ruff` run confirms the switch — no behaviour changed, only where each name is imported from.
