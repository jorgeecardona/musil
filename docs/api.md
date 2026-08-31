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

## Reconciler — `reconciler`

The controller / reconciler shape (a `desired` field the environment sets, an `actual` field the controller
drives toward it, goal `[]<>converged`) as a builder — the most common shape in modern infrastructure
(operators, sync engines, cache maintainers). `reconciler(get_desired=, get_actual=, set_actual=)` returns
`(converged, reconcile)`: the `converged` predicate for `check_liveness(everywhere=True)` and a fair
reconcile `Action` (tagged `fair="weak"` — the "ours" side of the fair-ours / unfair-faults discipline).
Compose it with the fault factories (`crash_actions`, channel loss) as unfair actions or `check_open`
environments.

::: musil.reconciler

## Faults — `crash_actions`, `partition_actions`

Fault-injection action factories for the explicit-state path (`check` / `explore` / `check_open`), so a
distributed model gets its standard faults from one call instead of a per-node copy-paste. `crash_actions`
builds crash (and optional revive) edges over a caller-declared node-liveness lens (`get_up` / `set_up`),
with `budget` bounding the number of simultaneous failures; `partition_actions` builds partition/heal edges
over a reachability lens (`get_reach` / `set_reach`), installing each caller-supplied split from the healed
state and restoring `healed` on heal. Keep the fault actions unfair (do not tag them or name them in
`fair`/`fair_strong`) so a liveness proof cannot lean on a fault being scheduled or healed.

::: musil.faults

## Clock — `bounded_clock`

A discrete clock bounded at a declared horizon, so a timeout model stays finite by construction
instead of by hitting `max_states` — and `binding()` says whether the bound was reached, i.e.
whether a green result covers the whole model or only the first `horizon` ticks.

::: musil.clock

## FSM bridge — `transition_actions`, `status_field_actions`, `replicated_transition_actions`

Build a model straight from an allowed-transitions table, so it can't drift from the code. A transition may
carry an `effect(state, src, dst)` (side effects on other fields) and an `also(state)` extra guard beyond
the table. `replicated_transition_actions` runs N copies of one table — one machine per instance, over a
FLAT state (per-instance `get`/`set_status` projections) — so a system of interchangeable entities keeps
cross-instance invariants expressible, where `compose`'s tuple state would not. `assert_covers_table`
checks the zero-drift claim mechanically: over the reachable space, every status change conforms to the
table (no transition the table forbids), so musil verifies it instead of a hand-rolled action-name test.

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

## Metrics & coverage — `state_space_metrics`, `coverage`, `invariant_coverage`, `solution_cardinality`, `portfolio_coverage`

How big and how branchy a design's reachable behaviour is, how many reachable states satisfy a goal,
and — because a green `check` does not say the behaviour you wrote was ever explored — which actions
never fired, were always enabled, or only ever self-looped (`coverage`), and which invariants are
load-bearing vs candidate-vacuous (`invariant_coverage`). `portfolio_coverage` asks the suite-level
question a single model cannot — how much of a declared external state machine the WHOLE set of models
exercises (reading state-field values across edges, unioned across the portfolio, diffed against the
table) — and `assert_covers` is its ratchet gate: no undeclared transition, dead edges exactly the named
blind spots (so they can only shrink), and a coverage-ratio floor.

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
`Eventually`, `Always`, `Until`, `Release`, `WeakUntil`), and `check_ltl`. The shapes that reduce soundly
onto the proven primitives (`G(state)` -> a safety invariant, `F(state)`, `G F(state)`, `G(a -> F b)` ->
`check_liveness`, with `fair`/`fair_strong`) take that path; everything else (`Until`/`Release`/`Next`/
arbitrary nesting) is decided by the general Büchi engine — the `Not(formula)` automaton via the GPVW
tableau, producted with the reachable graph, checked for an accepting run by SCC emptiness (Tarjan). On
violation the engine returns a counterexample **lasso** (`<init> -> stem -> cycle`) mapped back to model
states — a concrete run refuting the formula.

::: musil.ltl

## Temporal patterns — `always`, `absent`, `eventually`, `recurs`, `responds`

The Dwyer/Corbett specification patterns as one-call helpers: universality, absence, existence,
recurrence, and response. Each names a common temporal property and lowers onto the existing
`check`/`check_liveness`, so you pick the pattern instead of hand-encoding the temporal logic. This is
the global-scope family; the scoped and precedence patterns are not yet here.

::: musil.patterns

## Probabilistic — `reach_probability`, `reach_probability_mdp`, `expected_reward`, `expected_reward_mdp`

The exact probability of eventually reaching a target set, as a `fractions.Fraction` (no floating-point
error, no dependency). `reach_probability` treats the reachable graph as a discrete-time Markov chain
(each state's enabled actions carry a relative `weight` that normalises into a distribution over
successors) and solves it by Gaussian elimination over the rationals: target states have probability 1,
states that cannot reach the target have probability 0, and the rest solve `x_s = sum_s' P(s, s') x_s'`
(the standard three-way split, Baier & Katoen ch. 10). `reach_probability_mdp` adds nondeterministic
choice — a caller-supplied `moves` partitions each state's enabled actions into the moves a scheduler
picks between, with the actions within a move forming the distribution — and returns the maximal or
minimal reachability probability over all schedulers (`optimize="max"` / `"min"`), solved exactly by
policy iteration. The `"min"` case first pins the states from which a scheduler can avoid the target
forever to probability 0 (`S0min`), which is what keeps min policy iteration exact; see
`PROBABILISTIC_NOTES.md` for why that precomputation is needed and the max case is not. Both functions
take an optional `steps=k` for the exact probability of reaching the target within `k` transitions (a
finite unrolling, `steps=0` being the indicator of the target) instead of the unbounded probability.
`expected_reward` answers the dual question — the exact expected accumulated cost (default: number of
steps) to reach the target in a DTMC — solving `E(s) = sum P(s, s') (cost + E(s'))`. It raises when the
target is not reached almost surely (`reach_probability < 1`), because the expectation is then infinite.
`expected_reward_mdp` is the MDP version — the minimal expected cost over all schedulers (the stochastic
shortest path), solved exactly by policy iteration seeded with the max-reachability-optimal (hence proper)
policy; costs must be positive, and it raises when no scheduler reaches the target almost surely.

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
