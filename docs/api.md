# API reference

Everything below is re-exported from the top-level `musil` package, e.g. `from musil import Model, check`.

## Core — `check`, `Model`, `Action`

The model definition and the safety/deadlock/reachability checker.

::: musil.core

## Partial-order reduction — `explore_por`, `por_sound`, `independent`

Explore only an *ample set* of actions per state instead of every interleaving. `explore_por` takes a
caller-supplied `ample(state, enabled) -> subset`; `por_sound` validates that an ample choice preserves the
violable invariants (POR must not drop the path to a bug) before it is trusted — the same soundness
discipline as `symmetry_reduction_sound`. `independent` is the concrete per-state independence test
(commute + neither disables the other) the ample-set computation rests on.

::: musil.por

## Symmetry — `canonical_by_sorting`, `canonical_by_permutations`

Build the `canonicalize` that `check`/`explore` take, instead of hand-writing it. Sort the slices
when the components are anonymous; relabel the whole state under each permutation when something
names one. Either way, `symmetry_reduction_sound` still has to pass on a small instance first.

::: musil.symmetry

## Liveness — `check_liveness`

Eventually (`<>P`) and always-eventually (`[]<>P`) under weak and strong fairness.

::: musil.liveness

## Composition — `compose`

The interleaved product of independent component models.

::: musil.compose

## Channels — `channel_actions`, `send`

Model a message channel (reliable / lossy / duplicating; unordered, so reordering is free).

::: musil.channels

## Clock — `bounded_clock`

A discrete clock bounded at a declared horizon, so a timeout model stays finite by construction
instead of by hitting `max_states` — and `binding()` says whether the bound was reached, i.e.
whether a green result covers the whole model or only the first `horizon` ticks.

::: musil.clock

## FSM bridge — `transition_actions`, `status_field_actions`

Build a model straight from an allowed-transitions table, so it can't drift from the code.

::: musil.fsm

## Conformance — `generate_traces`, `replay`

Generate traces from the model and replay them against the real implementation.

::: musil.conformance

## Refinement — `check_refinement`, `RefinementMonitor`

Check that an observed run of the real system refines the model (each transition is a model edge or a
stutter) -- the oracle `simulate` uses to hold real code to a model-checked spec.

::: musil.refine

## Simulation — `simulate`, `Simulator`, `NetworkModel`, `FaultSchedule`

Deterministic simulation testing: run real event-driven node code under a controlled clock and a
fault-injecting network, reproducible from a seed, with invariants + refinement + a convergence goal
as the oracle. Beyond `NetworkModel`'s independent per-message loss, a `FaultSchedule` of **sustained,
heal-able** faults — network `Partition`s and node `Crash`es (with optional cold restart) — drives
VOPR-style **liveness** testing: after the faults heal, the system must converge to its goal (a
failure to do so is reported as `kind="liveness"`).

::: musil.sim

## Open systems — `check_open`, `check_liveness_open`, `EnvironmentSpec`, `Assumption`

Verify a system against adversarial external environments. Each `EnvironmentSpec` is a contract:
the non-deterministic *behaviors* the environment can exhibit (eviction, crash, wrong answer), the
*guarantees* it commits to, and the *assumptions* those guarantees rest on (following seL4's
two-layer assurance model: Klein et al., SOSP 2009). `check_open` composes by merging environment
behaviors into the system's action set (so the BFS explores every adversarial move) and environment
guarantees into the invariants. The result surface all `Assumption` objects that are not yet
`"verified"` as residual proof obligations.

::: musil.env

## Metrics & coverage — `state_space_metrics`, `coverage`, `invariant_coverage`, `solution_cardinality`

How big and how branchy a design's reachable behaviour is, how many reachable states satisfy a goal,
and — because a green `check` does not say the behaviour you wrote was ever explored — which actions
never fired, were always enabled, or only ever self-looped (`coverage`), and which invariants are
load-bearing vs candidate-vacuous (`invariant_coverage`).

::: musil.metrics

## Graph export — `to_dot`, `explore`

The reachable state graph and its Graphviz DOT rendering.

::: musil.graph

## Inductive proofs — `check_inductive`

Prove an invariant by k-induction over a finite domain, without enumerating the reachable set:
base plus step, returning a counterexample-to-induction (a state satisfying `I` with a successor that
breaks it) so you strengthen `I` rather than widen the scope. The "for all states" is made concrete by
enumerating a caller-supplied `domain` that must include unreachable states.

::: musil.induction

## LTL — `check_ltl`, formula AST

A linear-temporal-logic formula as pure data (`Atom`, `Not`, `And`, `Or`, `Implies`, `Next`,
`Eventually`, `Always`, `Until`, `Release`, `WeakUntil`), and `check_ltl`, which checks the fragment that
reduces soundly onto `check`/`check_liveness` (`G(state)`, `F(state)`, `G F(state)`, `G(a -> F b)`).
Anything outside that fragment raises `NotImplementedError` rather than returning a guessed verdict; the
general Büchi + nested-DFS engine that covers `Until`/`Release`/`Next`/arbitrary nesting lands
incrementally on top of this AST.

::: musil.ltl

## Temporal patterns — `always`, `absent`, `eventually`, `recurs`, `responds`

The Dwyer/Corbett specification patterns as one-call helpers: universality, absence, existence,
recurrence, and response. Each names a common temporal property and lowers onto the existing
`check`/`check_liveness`, so you pick the pattern instead of hand-encoding the temporal logic. This is
the global-scope family; the scoped and precedence patterns are not yet here.

::: musil.patterns

## Probabilistic — `reach_probability`, `reach_probability_mdp`

The exact probability of eventually reaching a target set, as a `fractions.Fraction` (no floating-point
error, no dependency). `reach_probability` treats the reachable graph as a discrete-time Markov chain
(each state's enabled actions carry a relative `weight` that normalises into a distribution over
successors) and solves it by Gaussian elimination over the rationals: target states have probability 1,
states that cannot reach the target have probability 0, and the rest solve `x_s = sum_s' P(s, s') x_s'`
(the standard three-way split, Baier & Katoen ch. 10). `reach_probability_mdp` adds nondeterministic
choice — a caller-supplied `moves` partitions each state's enabled actions into the moves a scheduler
picks between, with the actions within a move forming the distribution — and returns the maximal
reachability probability over all schedulers (`optimize="max"`), solved exactly by policy iteration.
`optimize="min"` is deferred (it needs the end-component precomputation; see `PROBABILISTIC_NOTES.md`).

::: musil.probabilistic

## Counterexamples — `minimize`, `as_regression_test`, `replay_actions`

Turn a raw counterexample into a debugging artifact: `minimize` delta-debugs a violating trace to its
minimal failing action subsequence, `as_regression_test` emits committable pytest source that replays it
and asserts the same invariant breaks, and `replay_actions` replays a fixed action-name sequence with no
search (the primitive the generated test runs).

::: musil.counterexample

## Model diff — `diff`, `ModelDiff`

The behavioral delta between two model versions: states reachable in only one, transitions present in
only one, and invariant outcomes that flipped on the shared states — so a refactor is reviewable as a
delta ("same reachable states and validity") rather than a leap of faith.

::: musil.diffing

## Profiling — `profile`

Where a slow `check` spends its time: per-phase timing (invariants, enumeration, enablement, `apply`,
`canonicalize`, visited-set) and the hottest actions/guards, so the fix is obvious rather than guessed.

::: musil.profiling

## Verdict caching — `check_cached`, `clear_verdict_cache`

Content-addressed caching for CI: return a cached verdict when the model (identified by a required
`version` string plus its readable structure) and options are unchanged, so an unchanged model is not
re-checked on every pipeline run.

::: musil.cache

## Coverage tracing — `no_trace`

A context manager that pauses the current thread's trace function (coverage or any `sys.settrace`
line-tracer) around the hot check, so the engine's inner loop is not line-traced under `pytest-cov`.

::: musil.tracing
