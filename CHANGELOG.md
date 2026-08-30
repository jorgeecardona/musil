# Changelog

All notable changes to musil are documented here. Versioning is [SemVer](https://semver.org/).

## [Unreleased]

### Added — `musil.ltl`: an LTL formula AST + `check_ltl` (first layer)

- An LTL formula as pure data — `Atom`, `Not`, `And`, `Or`, `Implies`, `Next`, `Eventually`, `Always`,
  `Until`, `Release`, `WeakUntil` — and `check_ltl(model, formula)`, the start of a full temporal-property
  layer (issue #2, item 2). This first cut checks the fragment that reduces SOUNDLY onto the existing
  proven primitives: `Always(state)` -> a safety invariant, `Eventually(state)` -> `<>P`,
  `Always(Eventually(state))` -> `[]<>P`, and `Always(Implies(a, Eventually(b)))` -> the response
  (leads-to) property, where `state` is any boolean combination of `Atom`s.
- Anything outside that fragment (`Until`, `Release`, `Next`, arbitrary nesting) raises
  `NotImplementedError` rather than returning a guessed verdict — the general engine (a Büchi automaton
  for the negated formula, its product with the reachable graph, emptiness via nested-DFS) lands
  incrementally on top of this same AST, at which point the fixed liveness forms and `musil.patterns`
  become sugar over it. Corpus entries pin the reductions against the traffic light's known verdicts.
- `check_ltl` pushes negations to the literals first (semantics-preserving LTL dualities: `!F = G !`,
  `!G = F !`, `!X = X !`, De Morgan, `!(a U b) = !a R !b`), so negated temporal forms reduce too — e.g.
  `!F p` becomes the invariant `G !p`, `!G p` becomes `<> !p`. `Implies` is kept unexpanded so the
  response shape survives. This is also the negation-normal-form preprocessing the general engine needs.
- A top-level conjunction splits: `model |= (a & b)` iff `model |= a` and `model |= b`, so conjoined
  specs like `G(safety) & G F(progress)` reduce (each conjunct independently; a failing conjunct's result
  is returned, an irreducible conjunct propagates the refusal). `LTL_NOTES.md` records the plan for the
  general Büchi + nested-DFS engine that will replace the remaining `NotImplementedError`s.
- `Buchi`: a Büchi automaton over model states (guards are predicates on the model state), with
  `has_accepting_run(graph)` — the emptiness check at the heart of LTL model checking: the product of the
  reachable graph and the automaton has an accepting run iff some reachable non-trivial SCC contains an
  accepting automaton state. Reuses musil's proven `tarjan`/`has_internal_edge` (the SCC machinery
  `check_liveness` already uses, now package-internal). This is the sound "back half" of the engine, built
  and validated first (hand-built automata for `F(!green)`, `F(!known)`, `G(!green)` on the traffic light);
  the GPVW `Not(formula) -> Buchi` front half and the wiring into `check_ltl` follow.

### Internal — `check`/`check_all`/`explore` share one successor kernel

- `check`, `check_all`, and `explore` now compute their canonical enabled successors through one lazy
  generator, `_successors` (the single place `canon(action.apply(state))` happens) — plus `_seed_frontier`
  / `_expand` shared by `check`/`check_all`. This is the exact spot that drifted in the 089aed0 bug
  (successors canonicalized in one path but not the other); it now lives in one place so it cannot diverge
  again. No behavior change: the known-verdict corpus (`tests/test_corpus.py`) pins identical reachable-state
  counts and verdicts across the refactor. `check`/`check_all`/`explore` share the kernel; `profile` keeps
  its own instrumented loop by design (it times `enabled`/`apply`/`canonicalize` separately, which the
  bundled kernel cannot), and the corpus now pins its full-sweep reachable count to `check`/`explore` so it
  cannot silently drift either. Move 1b (BFS unification) complete.

### Docs — genericize examples to invented / commonly-known systems

- Doc examples and docstrings now use invented or widely-known systems only (a generic control plane,
  `add_filter{field='status'}`), so nothing in the published docs or rendered API reference reflects any
  particular downstream deployment.

### Added — `musil.environments.distributed`: stateful storage/state fault contracts

- Two parameterized `EnvironmentSpec` factories for the fault classes that dominate a stateful distributed
  system's incidents ([issue #21](https://gitlab.com/jorgeecardona/musil/-/work_items/21), scope confirmed
  on the issue):
  - `credential_rotation(can_rotate, on_rotate)` — a credential invalidated mid-flight, with the assumption
    that the holder eventually re-authenticates rather than trusting a cached token.
  - `record_reality_divergence(can_diverge, on_diverge)` — a component's cached RECORD ceasing to match
    REALITY. Made the general abstraction, so "stale view after restart/cutover" AND "wrong/empty volume
    attached (record != reality)" are both usages of one factory rather than a domain-specific "volume" env.
- Deliberately not shipped: message lost/reordered/duplicated (already `musil.channels` + `sim.NetworkModel`
  — reuse those), and grace-window races (couple to `bounded_clock`; left downstream). Documented in
  `environments.md`.

### Docs — API reference now covers every module (was stuck near the 0.6.2 surface)

- `docs/api.md` was missing the modules added since 0.11.0, so the published site never surfaced them
  ([issue #19](https://gitlab.com/jorgeecardona/musil/-/work_items/19)). Added mkdocstrings sections for
  `induction`, `patterns`, `counterexample`, `diffing`, `profiling`, `cache`, and `tracing`, and named the
  new `invariant_coverage` / `check_liveness_open` symbols in the metrics/open-systems headings. A test
  (`test_docs_coverage`) now fails if any public module lacks a `::: musil.<module>` section, so the docs
  cannot silently drift behind the code again.

### Added — `check_liveness_open`: verify liveness under the same environments as `check_open`

- `check_liveness_open(system, *envs, goal=...)` is the liveness counterpart of `check_open`, so an
  `EnvironmentSpec`'s faults are not written twice (once as env behaviors for the safety `check_open`, once
  as hand-rolled unfair actions for `check_liveness`). From
  [issue #20](https://gitlab.com/jorgeecardona/musil/-/work_items/20). It merges every `env.behaviors`
  into the model and defaults `fair` to the SYSTEM's own action names, so environment behaviors are UNFAIR
  — an adversarial environment is never assumed to eventually help reach the goal. Pass `fair` explicitly
  to mark an env behavior fairly scheduled (e.g. "the network eventually delivers"); `fair=()` is strict.
- `goal`/`goal_name`/`everywhere`/`leadsto_from`/`fair_strong` pass through to `check_liveness`. Returns an
  `OpenLivenessResult` that surfaces the environments' unverified assumptions. Env SAFETY guarantees stay
  with `check_open` (safety); this form verifies the liveness goal under the same shared faults.

## [0.25.0] - 2026-08-29

Twelve features driven by the adoption issues (#5–#16) plus a coverage fix (#18), all stdlib-only so
`pip install musil` still installs zero third-party packages. Versions 0.13.0 through 0.24.0 are the
per-feature bumps the pre-commit hook made as these landed; none was published, so everything below ships
as 0.25.0.

### Fixed — `coverage()` is no longer blind for `actions_fn` models

- `coverage(model)` reported "all 0 actions fire and move" for a model whose action space comes from
  `Model.actions_fn`, because it enumerated the empty static `model.actions`
  ([issue #18](https://gitlab.com/jorgeecardona/musil/-/work_items/18)). It now derives the action universe
  from the names `actions_fn` offers across the reachable states (so a never-enabled kind is still counted).
- `coverage(model, key=...)` / `coverage_of(graph, model, key=...)` take a `name -> kind` bucketer: an
  `actions_fn` model whose per-state actions carry unique names (e.g. `add_filter{field='status'}`) reports
  usefully with `key=lambda name: name.split('{')[0]`. Static-`actions` models are unchanged when no key is
  given.

### Added — `musil.patterns`: the Dwyer specification patterns as one-call helpers

- `always(p)` (universality), `absent(p)` (absence), `eventually(p)` (existence `<>p`), `recurs(p)`
  (recurrence `[]<>p`), and `responds(trigger, response)` (response `[](trigger -> <>response)`) name the
  common temporal properties and lower each onto the existing `check`/`check_liveness`, so a team picks the
  pattern instead of hand-encoding the temporal logic. From
  [issue #16](https://gitlab.com/jorgeecardona/musil/-/work_items/16). Each returns its underlying result
  (`Result` for the safety patterns, `LivenessResult` for the liveness ones); both are `Verdict`s, so
  `assert_ok` works uniformly.
- Scope: this v1 is the GLOBAL-scope family. The scoped variants (after / between / until a delimiter) and
  the precedence family (which need the state to carry history) are deliberately deferred and noted on the
  issue.

### Added — `diff`: the behavioral delta between two model versions

- `diff(model_a, model_b, *, canonicalize=...)` explores both and reports states reachable in only one,
  transitions present in only one, and invariant outcomes that flipped on the shared states (a
  `ModelDiff` with `.equivalent`). From
  [issue #14](https://gitlab.com/jorgeecardona/musil/-/work_items/14): makes a refactor reviewable as a
  behavioral delta ("same reachable states and validity") rather than a leap of faith. Reads only the two
  reachable graphs, so it is O(states + transitions); states must be hashable (it runs `explore`).

### Added — `no_trace`: spare musil's hot loop from coverage/tracing overhead

- `no_trace()` is a context manager that pauses the current thread's trace function (coverage, or any
  `sys.settrace` line-tracer) for its block and restores it after — a no-op when nothing is tracing, so it
  costs nothing outside coverage/debug runs. From
  [issue #13](https://gitlab.com/jorgeecardona/musil/-/work_items/13): a check that ran ~10s bare took
  ~120s under CI coverage because line-tracing the engine's hot loop is pure waste (nobody measures
  musil's own coverage). Wrap only the check; the docstring also documents the coarser
  `[tool.coverage.run] omit` route. Dependency-free (just `sys`).

### Added — `as_regression_test` / `replay_actions`: pin a counterexample as a committable test

- `as_regression_test(model, result)` emits pytest SOURCE that replays the (minimized) counterexample and
  asserts the same invariant breaks — a fast, deterministic regression test that pins the exact
  interleaving without re-running the exhaustive search. From
  [issue #15](https://gitlab.com/jorgeecardona/musil/-/work_items/15); feeds from `minimize` (#12).
- `replay_actions(model, names)` is the primitive it emits against: replay a fixed action-name sequence
  from init, checking every invariant along the one path (no search), returning the `Result`. Raises if a
  named action is no longer available/enabled, so a stale regression test fails loudly rather than
  silently passing.

### Added — `minimize`: delta-debug a counterexample to its minimal failing subsequence

- `minimize(model, result)` drops actions from a violating trace and re-checks that replaying the reduced
  sequence from init still breaks the SAME invariant, returning a new `Result` with the minimal action
  sequence (greedy 1-minimization). From [issue #12](https://gitlab.com/jorgeecardona/musil/-/work_items/12).
- Honest scope: a `check`/`check_all` counterexample is already BFS-shortest, so no strict subsequence of
  it can violate and `minimize` returns it unchanged. Its value is on traces that are NOT step-minimal — a
  long simulation (VOPR) run, an externally assembled sequence, or any trace carrying actions irrelevant
  to the violation — and as the seed for a committable regression test (#15). Only invariant
  counterexamples are minimized (an `ok` result or a deadlock passes through); if the trace cannot be
  replayed deterministically it is returned unchanged rather than risking a wrong reduction.

### Added — `check_inductive`: prove an invariant by k-induction over a finite domain

- `check_inductive(model, invariant, domain, *, k=1)` proves an invariant INDUCTIVELY — base (`I` holds
  within `k-1` steps of init) plus step (along every path whose first `k` states satisfy `I`, the next
  does) — and on failure returns a **counterexample-to-induction**: a state satisfying `I` with a successor
  that breaks it, so the author strengthens `I` instead of widening the scope. From
  [issue #6](https://gitlab.com/jorgeecardona/musil/-/work_items/6).
- The "for all states s" is made concrete WITHOUT an SMT solver by quantifying over a caller-supplied
  finite `domain` (every assignment of the state's bounded variables) — the enumerable fragment, where
  exhaustion is a complete, sound decision procedure. The `domain` MUST include unreachable states:
  1-induction over only the reachable set is trivially true for a passing model, so the unreachable states
  are exactly where a counterexample-to-induction lives. `k > 1` proves invariants that are true but not
  1-inductive. The step only follows enabled transitions, so a guarded partial `apply` stays in bounds.
- Honest boundary (see `INDUCTION_NOTES.md`): with no finite domain to enumerate — an infinite value range,
  or an unbounded number of components — this is a bounded refutation, not a proof; closing that needs a
  symbolic engine (an optional `z3` extra) kept out of the dependency-free core.

### Added — `check_cached`: content-addressed verdict caching for CI

- `check_cached(model, version=...)` returns a cached verdict when the model and options are unchanged,
  else runs `check`, stores the `Result`, and returns it — so an unchanged model is not re-checked on
  every CI run ([issue #10](https://gitlab.com/jorgeecardona/musil/-/work_items/10): a ~5-20s exhaustive
  check running on every pipeline even when nothing changed). `clear_verdict_cache(cache_dir)` empties it.
- `version` is REQUIRED and is the caller's soundness obligation: actions, invariants and `terminal` are
  opaque callables, and a function's `repr` carries a per-run address, so the LOGIC identity has to be an
  explicit string the caller bumps when a body changes. The digest additionally folds in what CAN be read
  stably — action/invariant names, initial-state reprs, options, and which opaque hooks are present — so a
  structural edit invalidates the cache automatically; only a changed body under an unchanged name needs
  the bump. The cache is a directory of pickle files (holds the full trace with live states); load only a
  cache you produced, and writing is best-effort so a read-only dir just runs the check.

### Added — `canonical_by_fields`: declarative symmetry reduction

- `canonical_by_fields(*fields, key=...)` derives a `canonicalize` by SORTING each named field (each of
  which holds a collection of interchangeable items) into a canonical order — the same thing
  `canonical_by_sorting` builds, without hand-writing the `get`/`put` accessors, for the common case where
  the interchangeable components already live in one field (a tuple of per-worker slices, a multiset of
  ids, a pool of domain values). Works on frozen dataclass and pydantic v2 states. From
  [issue #11](https://gitlab.com/jorgeecardona/musil/-/work_items/11): a reducer with 5 interchangeable
  dimensions where hand-writing the relabelling was fiddly enough that the test scoped down to 2 instead.
- Expressed as a `canonicalize` you pass to `check`/`explore` (the same shape as the other two
  constructions), not a new `Model` field, so the soundness obligation stays visible at the call site.
  Declarative does NOT mean automatically sound: it removes the boilerplate, not the obligation — an
  order-sensitive invariant or a field that names a component still makes the sort unsound, and
  `symmetry_reduction_sound` still has to pass on a small instance first.

### Added — `invariant_coverage`: which invariants are load-bearing vs candidate-vacuous

- `invariant_coverage(model)` / `invariant_coverage_of(graph, model)` are the dual of `coverage` (which is
  about actions). Over the reachable space each invariant is `load_bearing` — some GUARDED-OFF action,
  applied to a reachable state, WOULD violate it, so a guard is what keeps it true — or `candidate_vacuous`
  — nothing ever threatens it, so it holds by construction and a green check says nothing about it.
  `threats` maps each load-bearing invariant to the actions that would break it. From
  [issue #9](https://gitlab.com/jorgeecardona/musil/-/work_items/9): telling `unique-ids` (holds by
  construction) from `kpi-never-resized` (enforced only because a guard never offers resize).
- The practical form of the vacuity idea `coverage` dropped as too naive: reachability + near-misses over
  the graph, not reasoning about opaque invariant antecedents. It applies guarded-off actions to reachable
  states and asks whether the result violates each invariant; a partial `apply` that relies on its guard
  (and raises without it) is skipped rather than crashing the analysis. Analyses the static `model.actions`
  and costs O(states x actions x invariants), so run it as an audit next to `check`, not inside it.

### Added — `profile`: where a slow `check` spends its time

- `profile(model)` runs the same reachable sweep as `check`, timed, and returns a `Profile`: time split
  by PHASE (invariants, enumeration, enablement, `apply`, `canonicalize`, visited-set), the hottest
  ACTIONS by cumulative `enabled` + `apply` time and call count, states/second, and the dominant phase.
  From [issue #8](https://gitlab.com/jorgeecardona/musil/-/work_items/8): a check ran ~120s under CI
  coverage and diagnosing it meant reverse-engineering that a guard rebuilt an expensive menu ~100k
  times — a profiler shows that in one run.
- Separate from `check` (not a `check(profile=True)` flag that would change the return type), matching
  `coverage`/`state_space_metrics`. Profiles the FULL sweep, not `check`'s early exit — a passing-but-slow
  check is what you profile. Accepts `canonicalize` and `key` like `check`. An instrumented sibling of
  `check`'s BFS: timing every call adds overhead, so the RELATIVE phase split is the signal, not the
  absolute seconds.

### Added — `Model.footprint`: memoize an expensive `actions_fn` across states

- `Model.footprint` is a `state -> hashable` projection of the sub-state `actions_fn` reads. When set,
  `check` / `check_all` / `explore` cache the enumerated action list on `footprint(state)` and reuse it
  for every state that shares a footprint, so an expensive menu builder runs once per footprint instead
  of once per state. The framework-level version of the `lru_cache` such callers hand-write. Real case
  (from [issue #7](https://gitlab.com/jorgeecardona/musil/-/work_items/7)): a reducer whose per-tile
  menu depends on one tile but recurs across ~40 distinct tiles over ~2600 states — ~40 builds instead
  of ~7800.
- `footprint_sound(model, states)` is the gate. Unlike `canonicalize`, a footprint does NOT quotient the
  space, so an unsound one does not shrink the sweep — it hands a state the WRONG memoized menu, so
  successors go wrong and reachable states (and the violations only they reach) can be missed. The
  validator groups the sampled states by footprint and returns False if any group's `actions_fn` menus
  differ (by action name). Pass `explore(model).states` for a hashable model, or a representative sample
  for a non-hashable one (footprint's target case, checked via `key=`); like any sampling gate it can
  only disprove soundness on the states it sees.
- Supersedes [issue #5](https://gitlab.com/jorgeecardona/musil/-/work_items/5): the guard-memoization
  ask there was first answered by `actions_fn` (0.13.0); `footprint` closes the residual "still
  recomputed once per state" gap.

### Added — `coverage`: a green `check` does not say your behaviour was ever explored

- `coverage(model)` / `coverage_of(graph, model)` report, over the reachable graph, the actions that
  are **never enabled** (dead — a guard bug that silently removes an interleaving the author believed
  was covered), **always enabled** (the guard never guards), and **only ever self-looping** (fires,
  changes nothing). Sets of names, not accusations: an always-enabled `Idle` or adversarial `crash`
  is legitimate, and only the author knows which.
- Reads the graph's recorded edges rather than re-calling `enabled`, so it is O(edges) and stays
  correct under symmetry reduction — a reduced graph stores canonical successors, so re-applying the
  actions and comparing would misjudge which firings moved. A test pins that against
  `canonical_by_sorting`.
- Deliberately **not** a field on `Result`: `check` early-exits at the first violation, so the graph
  it saw is partial and coverage computed from it would be wrong in the direction that matters —
  actions look dead because the sweep stopped, not because they cannot fire.
- Under `truncated`, `dead_actions` means only *not yet seen enabled*; the rendering says
  `COVERAGE INCONCLUSIVE` rather than calling anything dead.
- `musil.metrics` also reaches the API docs for the first time — it had no section in `api.md`, so
  `state_space_metrics`, `metrics_of` and `solution_cardinality` were undocumented on the site too.
- From [issue #2](https://gitlab.com/jorgeecardona/musil/-/work_items/2), item 1. The vacuity half of
  that item was dropped with the reason recorded: it proposed flagging invariants that hold across
  the whole reachable space, but in a passing model *every* invariant does — the signal would fire on
  every healthy model. Real vacuity detection needs the invariant's antecedent, and musil invariants
  are opaque callables.

### Added — checking ergonomics for rich, real-world state machines

- **`key=` on `check` / `check_all`** — a `state -> hashable` identity used only for the visited-set +
  trace bookkeeping, so states that are NOT themselves hashable (a pydantic model, a dataclass with
  `list` fields) can be checked directly, with no wrapper type. Distinct from `canonicalize`: no symmetry
  obligation, and the rich states are kept for the trace. Must be INJECTIVE over reachable states, though:
  a collision prunes a state and all its successors, silently dropping reachable states (there is no
  validator, unlike `canonicalize`). (`explore` and its tools still need hashable
  states.)
- **`Model.actions_fn`** — a `state -> Iterable[Action]` that supplies the actions available IN a state,
  for a STATE-DEPENDENT action space (a `possibleActions(state)`/offered-menu enumerator, or a bounded
  parameterized algebra whose enabled bindings depend on the state) instead of hand-guarding a large
  static product. Honoured by `check`, `check_all`, and `explore`.
- **`check_all(distinct_by=...)` accepts a callable** `(invariant_name, reason) -> hashable` to bucket
  violations by a caller-defined CLASS — for when the reason embeds variable detail (ids, counts) that
  would otherwise explode into many spurious "distinct" entries.
- **`ActionSchema` + `enumerate_actions`** — declare a parameterized action (name, typed parameter slots
  with BOUNDED domains, `apply`/`enabled` taking those params as kwargs); `enumerate_actions` expands the
  cartesian product into concrete `Action`s (bound by value; the binding is encoded in each action's
  name). Makes the bounded-action-algebra pattern first-class.
- **`format_trace(render=...)` and `format_trace_diff`** — customise per-state rendering; the diff variant
  shows only the FIELDS THAT CHANGED between consecutive states (dataclass / pydantic / Mapping), so a
  counterexample over rich states reads as deltas instead of full dumps.

### Fixed

- **`check` now canonicalizes SUCCESSOR states**, not only the initial states (`nxt = canon(action.apply
  (state))`), matching `explore`. Previously `canonicalize=` was effectively a no-op in `check` (symmetry
  reduction never kicked in on successors).
- **A single pydantic model is no longer mistaken for a collection of initial states.** `_is_state_collection`
  now treats any dataclass instance or pydantic model (which is iterable in v2) as ONE state, so
  `Model(init=SomePydanticModel(...))` is not shredded into `(field, value)` tuples.

## [0.11.0] - 2026-08-12

Four of the five additions from
[issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), raised by adopting musil in a
downstream workspace. All four are stdlib-only, so `pip install musil` still installs zero
third-party packages. The fifth — a Hypothesis strategy bridge — is the one that cannot be built
without a dependency and is left open as a decision rather than answered by writing the code.

(Versions 0.8.0 through 0.10.0 are the per-feature bumps the pre-commit hook made as these landed;
none was published, so everything below ships as 0.11.0.)

### Added — `canonical_by_sorting` / `canonical_by_permutations`: derive the symmetry reduction

- `check(model, canonicalize=...)` has always accepted a symmetry reduction and
  `symmetry_reduction_sound` has always been able to *grade* one. The step between was missing:
  turning "these N components are interchangeable" into the function. Hand-writing it is where the
  mistakes live, and an unsound canonicalizer silently drops reachable states.
- `canonical_by_sorting(get=..., put=...)` sorts the per-component slices — O(N log N), the one that
  scales. For N workers over 3 values it turns `3 ** N` states into the multisets of size N: 243 → 21
  at N=5. Tested at N ∈ {3, 4, 5} against the exact combinatorial count, with
  `symmetry_reduction_sound` asserted in the same test, because a reduction that shrinks and lies is
  worthless.
- `canonical_by_permutations(identities, relabel)` takes the orbit minimum under every permutation —
  correct when something *names* a component (a leader index, an owner, a route id in a message),
  where sorting breaks the reference while leaving the state well-formed. Factorial in the number of
  identities, so `max_permutations` (default 5040 = 7!) makes that a loud error naming the sorting
  alternative rather than a hang.
- Three tests make the distinction concrete on one model whose `leader` field indexes the workers:
  sorting *invents* a violation the real model never has (and the gate rejects it), a relabel that
  moves the counts but forgets the leader fails the same way, and the full relabel is sound and
  reduces.
- Neither construction removes the obligation to run `symmetry_reduction_sound` on a small instance
  first. A model that grows a `leader` field next year makes a previously-sound sort unsound, and
  nothing about the sort itself changes to say so.
- Prompted by [issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), item 2. Partial-order
  reduction stays deferred (REDUCTION_NOTES.md); symmetry pays off sooner for these models.

### Added — `bounded_clock`: timeouts in the explicit-state layer, finite by construction

- `sim` has a virtual clock; `Model`/`Action` had none, so every timeout model (a wait with a
  deadline, a retry ladder that gives up) hand-rolled a tick action plus a bound. The bound is the
  easy thing to get wrong and getting it wrong is quiet: an unbounded clock does not fail, it hits
  `max_states` and returns `Result(ok=True, truncated=True)` — which reads as success to `if result:`
  and prints as `OK — 1000000 states, no violations (TRUNCATED at cap)`.
- `bounded_clock(get=..., put=..., horizon=..., name="clock")` returns a `BoundedClock` with the tick
  `action` (enabled exactly while `now < horizon`, so the clock adds `horizon + 1` values — linear,
  and finite by construction), `now`, and `at_horizon`. Same `get`/`put` accessor style as the
  channel kit; the clock lives in a field of your own state.
- `clock.binding(graph)` answers the question a bound raises: **was the horizon reached?** False means
  the model finished on its own and a green result is about the whole model. True means the green
  result only says "no violation within `horizon` ticks" — a weaker claim that should not be quoted
  as the stronger one. A test shows the case where no horizon is large enough, because the model can
  always tick: the answer is to change the model, not the number.
- Deadlines stay ordinary guards over `now` (`s.now >= armed_at + delay`); this supplies the time
  they read and the bound that keeps them finite, not the timeout semantics.
- `terminal=clock.at_horizon` is expected: at the bound the tick is disabled, so a state whose only
  move was the tick has none left and `check` calls it a deadlock. Forgetting it therefore fails
  loudly with a trace ending at the horizon rather than answering something wrong quietly, and a test
  pins that behaviour.
- Prompted by [issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), item 3.

### Added — `areplay` and `acheck_refinement`: hold an *async* implementation to the model

- `areplay(traces, step_fn=..., project=..., start=...)` — `replay` for a real system that has to be
  awaited. `step_fn` is awaited; `project` may be sync or a coroutine function (reading the real
  system usually awaits too). Same arguments, same `ConformanceResult`, same divergence indices.
- `RefinementMonitor.aobserve` and `acheck_refinement(model, observations, abstraction)` over an
  `AsyncIterable` — for observations that are *produced* by awaiting (polling a live service, an
  async generator) rather than collected into a list first. Streaming matters beyond convenience: a
  violation stops the polling instead of being found after an unbounded run has been drained.
- The abstraction may now be async; `RefinementMonitor.observe` raises `TypeError` pointing at
  `aobserve` when handed one, rather than abstracting every observation to a coroutine object and
  reporting a bogus `unknown-state` violation.
- Why it was needed: the sync `replay` forces one `asyncio.run` per step. That cannot be called from
  a running loop, so no `async def` test can use it — and it gives every step its own event loop, so
  a connection pool or open transaction created in one step is dead in the next. A test asserts both
  halves: the workaround raises `RuntimeError` inside a coroutine, and `areplay` runs a whole trace
  on the loop that opened the connection.
- `replay` and `areplay` drive one shared loop (`_drive`, a sans-io generator): the trace
  bookkeeping, the step counters and the divergence report exist once and cannot drift apart. A test
  asserts the two agree on `trace_index`, `step_index`, `action`, `expected`, `actual` and
  `steps_run` for the same buggy implementation.
- Still no dependency — `asyncio` is stdlib. Prompted by
  [issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), item 1.

### Added — `assert_ok`: the counterexample survives the test runner

- `assert_ok(result, message=None)` raises `AssertionError(str(result))`, so a failing check inside
  a test reports the rendered trace (`INVARIANT VIOLATED: … / Init: … / → action: …`) instead of the
  result's repr. `assert check(model)` reported the repr, and pytest shortens a long repr by eliding
  its middle: the counterexample came out as `trace=(Step(action='<init>', s...Step(action='inc',
  state=S(n=3)))` — the *initial state cut* — followed by the whole `Model` repr, lambda addresses
  and all. The information was not merely ugly, it was incomplete.
- Works on every musil result (`Result`, `LivenessResult`, `ConformanceResult`, `RefinementResult`,
  `OpenResult`, `SimReport`) via the structural `Verdict` protocol, and sets `__tracebackhide__` so
  pytest does not reprint the elided repr as the helper's own frame. Still no dependency: it raises
  a plain `AssertionError`, so `unittest` and bare `assert` get the same message.
- Prompted by feedback from adopting musil in a downstream workspace
  ([issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), item 5). The pytest *plugin*
  from that report was deliberately not built: an entry point would make pytest a packaging concern
  of a package whose headline property is `dependencies = []`, and a plain function recovers the
  elided trace, which was the entire measured defect.

## [0.7.0] - 2026-07-30

Prompted by feedback from verifying the discrete half of a Modelica simulation engine in
[pymodelica](https://gitlab.com/jorgeecardona/pymodelica) — see `IDEAS.md`.

### Added — `reaches` and `fixed_points`: reachability and confluence as first-class results

- `reaches(graph, predicate)` — the states from which a matching state is still reachable (BFS
  over the reversed edges), with the complement being the *trap*. The weaker cousin of liveness:
  "can it still get there?" (AG EF) rather than "must it get there?" (AG AF). `reaches(g, p) ==
  set(g.states)` says the goal stays available from every reachable state — e.g. "`fmi3FreeInstance`
  is legal in every FMI mode". Users were hand-rolling exactly this reverse BFS; `check_liveness`
  now uses it internally too.
- `fixed_points(model)` — for each initial state *separately*, the distinct terminal states (no
  outgoing edge) its runs can end in. `.confluent` asserts no single start can settle in two
  different places, i.e. the fixed point does not depend on the order actions fired — validating,
  e.g., that event iteration is order-independent when nothing chooses the order on purpose.
  Per start deliberately: different starts settling differently is what a latch is for.
- Both prompted by feedback from modelling the FMI 3.0 calling sequence and event iteration in
  [pymodelica](https://gitlab.com/jorgeecardona/pymodelica).

### Fixed — `everywhere=True` documentation described a different (weaker) property

- README and the `check_liveness` docstring said "from any reachable state, P must always still be
  *reachable*" — which reads as reachability (AG EF). The implementation checks *always eventually*
  P (AG AF): a reachable cycle that never reaches P is a violation even when P stays reachable
  from inside it, unless fairness rules the loop out. The checker was right and the prose was
  wrong — a user modelling FMI wrote the wrong property from the old wording. The prose now states
  the checked property and points to `reaches` for the weaker question.

### Added — `protocol_actions`: transition tables whose edges are labelled by the call

- `transition_actions` covers `{state: {states it may become}}`. A *published protocol* has a
  different shape: `{state: {operation: where it leaves you}}`, where the edges are labelled by the
  call and most calls are legal without moving at all. `protocol_actions` builds a model from that
  table directly, and `protocol_operations(table, state)` lists what a runtime guard should allow.
- The zero-drift argument, one level up: a protocol table is what a guard needs anyway — "is this
  call legal here, and where does it leave me" — so pointing the checker at it means the sequence
  being verified is the sequence being enforced, not a second description of it.
- Motivated by the FMI 3.0 calling sequence in
  [pymodelica](https://gitlab.com/jorgeecardona/pymodelica), where one table has to serve an
  exported FMU's guard, an importer's driver and the checker. Its first useful answer there was
  "this mode is unreachable" — a state transcribed from the specification into the wrong
  interface's table, which reading it will not show you.

### Fixed — a `str` (or `StrEnum`) state was taken apart into its characters

- `Model(init="red", ...)` was read as *four* initial states — `"r"`, `"e"`, `"d"` — because the
  "several initial states" heuristic accepted anything iterable that was not a dataclass. It did
  not raise; it checked a different model and reported OK, which is the worst way for a checker to
  be wrong. `str` and `bytes` are now always one state.
- This bites hardest exactly where a plain-string state is most natural: a `StrEnum` naming the
  states of a published protocol (`Instantiated`, `Event Mode`, …), which is a `str` subclass. Found
  while modelling the FMI 3.0 calling sequence in
  [pymodelica](https://gitlab.com/jorgeecardona/pymodelica), where every mode came back
  "unreachable" and the states were single letters.

## [0.6.0] - 2026-06-28

### Added — leader-election and vote-tallying examples

- **`examples/leader_election.py`** — quorum-based leader election (the Raft/Paxos essence). Three
  results: no quorum → two leaders in one term (split brain); a majority → *at most one leader per
  term* (safe); and "a leader is eventually elected" is FALSE in general — the split-vote livelock,
  which is why real Raft needs randomized election timeouts. Docs page, subprocess test, nav entry.
- **`examples/voting_tally.py`** — vote-tally integrity: a racy read-then-write count drops a vote
  (lost update); the atomic count is correct (every eligible voter at most once, every ballot counted
  exactly once, tally == ballots). Explicitly delimits scope — ballot secrecy is a cryptographic
  property, not a state-machine one, so it is out of scope. Docs page, subprocess test, nav entry.

### Added — symmetry reduction (opt-in, with a soundness gate)

- **`check(..., canonicalize=f)`** and **`explore(..., canonicalize=f)`** enable symmetry reduction:
  each state is mapped to a canonical representative of its symmetry-equivalence class, so
  interchangeable components (sort the per-worker slices, etc.) collapse and the state space stops
  blowing up combinatorially. Opt-in; `canonicalize=None` is the unchanged default.
- **`symmetry_reduction_sound(model, f)`** is the validation gate (the project's "ships only with a
  soundness check" rule for reductions): it explores fully and reduced and confirms both the
  canonical-quotient *coverage* and the set of *violable invariants* agree. Coverage alone passes for
  a lossy projection that merges non-equivalent states; the invariant-set check catches that — so the
  gate rejects an unsound `canonicalize` (or a non-class-constant invariant). Methodology: validate on
  small instances, then trust `canonicalize` on large ones. Does not cover deadlock-freedom.
  Reduced counterexample traces are witnesses *up to symmetry*. Tests in `tests/test_symmetry.py`.

### Added — `invariant_from_violations` adapter

- **`musil.invariant_from_violations(checker, describe=…)`** adapts an external checker that returns a
  sequence of violation objects (empty = OK) into a musil invariant: `True` when empty, else the first
  violation's `describe(...)` string (a reason). The idiomatic, footgun-free way to drive a real
  `world -> [Violation]` checker as an invariant — avoids the `not checker(s)` trap where a truthy
  reason string reads as "holds". Documented that trap in the `Invariant` docstring. Test in
  `tests/test_core.py`.

### Added — `reachable_violations` (exhaustive audit)

- **`musil.reachable_violations(model)`** returns every `(reachable state, broken invariant)` pair as
  `StateViolation(state, invariant, reason)` — where `check` stops at the first counterexample, this
  lists them all. For audits and *simplification*: enumerate the exact set of invalid states a model
  can reach (e.g. to derive which cross-resource combinations a guard must exclude). Same invariant
  semantics as `check` (string return = violation with reason). Test in `tests/test_core.py`.

### Added — leads-to (response) liveness

- **`check_liveness(..., leadsto_from=Q)`** checks the response property `[](Q -> <>P)` — *whenever
  Q holds, P eventually follows*. This is the untimed "no resource gets stuck" property (e.g. every
  service that enters `placed` eventually reaches `running`). Correctly **weaker** than
  `everywhere=True`: a ¬P cycle no Q-state can reach is not a violation. Implemented by reusing the
  existing `<>P` analysis seeded from every reachable Q∧¬P state — no new cycle logic — with a
  soundness-distinguishing test (holds where `everywhere` fails). Tests in `tests/test_liveness.py`.

### Added — FIFO (ordered) channel kit

- **`musil.fifo_channel_actions` / `musil.fifo_send`** — the order-preserving counterpart to
  `channel_actions`. In-flight messages are an ordered tuple; only the **head** is deliverable (and,
  if `lossy`, droppable), so messages arrive in send order with no reordering. For sequence-number
  protocols (alternating-bit, sliding-window) and any link whose correctness assumes order — where
  the unordered `channel_actions` would wrongly explore reorderings (the ABP example had to hand-roll
  this). Caller bounds the queue from the sender side. Tests in `tests/test_channels.py`.

### Added — `multi_status_field_actions` for multi-resource models

- **`musil.multi_status_field_actions(tables)`** — build the interleaved product of several status
  machines over one dataclass in a single call: `tables` maps each field name to its `ALLOWED`-style
  table, and actions are namespaced `"<field>:<src>-><dst>"`. Removes the per-field
  `transition_actions` boilerplate every multi-resource model (e.g. a control-plane `World` with
  `node`/`service`/`cert` fields) was hand-rolling. Test in `tests/test_fsm.py`.

### Added — invariants can carry a reason

- **`Invariant` may return `str`.** An invariant now returns `bool | str | None`: `True` holds,
  `False`/`None` is a violation (as before), and a **string** is a violation that carries a
  human-readable *reason*, surfaced on the new `Result.reason` field and in `str(result)`. Backward
  compatible (only non-empty strings change meaning, which no bool predicate returned). This makes
  wrapping a richer external checker first-class: e.g. driving a real `check(world) -> [Violation]`
  and returning `f"{v.invariant}: {v.message}"` so the counterexample names which sub-rule and entity
  broke, instead of a single generic invariant name. Tests in `tests/test_core.py`.

### Added — Alternating Bit Protocol example

- **`examples/alternating_bit.py`** — ABP as four `check`/`check_liveness` calls. (1) On musil's
  **unordered** channel kit, `check` proves ABP *unsafe*: the one-bit counter wraps and a
  two-generations-old frame is wrongly accepted — ABP assumes FIFO, which the kit does not model.
  (2) On a hand-rolled single-slot FIFO link with the bit stripped, the duplicate is delivered twice
  (3-step counterexample). (3) Real ABP on the FIFO link is safe. (4) Eventual delivery over the
  lossy link is **false under weak fairness** (drop-forever lasso) and **true under strong fairness** —
  the canonical demonstration of why `fair_strong` exists. Docs page, subprocess test, and nav entry
  added. Surfaces an improvement for `musil.channels`: a `fifo=True` (ordered) channel mode, so
  sequence-number protocols need not hand-roll their own.

### Changed — TCAS II example revised to protocol-accurate coordination model

- **`examples/tcas.py`** — four scenarios (was three). VRC constraint broadcast now modeled
  accurately: `Aircraft` gains a `vrc_received` field carrying the Mode S coordination constraint
  (`"no-climb"` / `"no-descend"`). The intruder's RA is forced by the constraint it received
  from own, not computed symmetrically. This matches the actual UF=16/DF=16 Mode S coordination
  protocol (BDS register 0x30, bits MB:23–26; RTCA DO-185B / ICAO Annex 10 Vol. IV).

- **New scenario 4 — v7.1 reversal + Tenerife.** `reversal_model` adds the `own:ra=reversed`
  system action (DO-185B v7.1 mechanism: own reverses when intruder has not maneuvered within
  the timing window; one reversal per encounter). `tenerife_env` injects
  `intruder:maneuvers-with-old-ra` (intruder executes its original RA while re-coordination is
  incomplete). `check_open` finds the counterexample in 7 steps and surfaces
  `INTRUDER_FOLLOWS_REVERSAL` as a residual obligation. Models the 2011 Tenerife near-collision
  (CIAIAC A-032/2011; Thomas Cook / Finnair).

- **`docs/paper.md`** — § 5.4 added: TCAS II as a fourth evaluation case study, including
  connection to Lynch's Hybrid I/O Automata model (Livadas, Lygeros & Lynch 2000) and the
  ACAS X formal verification line (Jeannin, Platzer et al. 2015/2017). References section
  updated with seven TCAS/ACAS formal verification papers.

## [0.5.0] - 2026-06-24

### Added — academic paper draft

- **`docs/paper.md`** — paper draft targeting OOPSLA tool track / ISSTA / ECOOP tool track.
  Stakes the claim that musil is the first Python library to unify explicit-state model
  checking, deterministic simulation testing, and open-system contract verification.
  Formal grounding: Interface Automata (de Alfaro & Henzinger, ESEC/FSE 2001),
  contract-based design (Benveniste et al., INRIA RR-8147, 2012), I/O Automata
  (Lynch & Tuttle, 1987), seL4 assumption layering (Klein et al., SOSP 2009).
  Sections: Abstract, Introduction, Background and Related Work, Design, Implementation,
  Evaluation (three case studies), Limitations, Conclusion, References.

- **`mkdocs.yml`** — added paper to site nav as "Paper draft".

## [0.4.0] - 2026-06-24

### Added — pre-built adversarial environment library

- **`musil.environments`** — new sub-package with five production-grade adversarial environments,
  each shipping named `Assumption` constants (with real source citations), an `EnvironmentSpec`
  factory for `check_open`, and an `AdversarialNode` factory for simulation:

  - **`k8s`** — pod eviction, OOM kill. Assumptions: `k8s:node-capacity`,
    `k8s:scheduler-liveness`, `k8s:eviction-rate-bounded` (all unverified; cites Kubernetes docs).
    Factories: `pod_eviction`, `eviction_notifier`, `oom_notifier`.

  - **`aws`** — API throttling, request timeouts. Assumptions: `aws:s3-eventual-delivery`,
    `aws:region-availability`, `aws:throttle-transient` (unverified); `aws:iam-correctness`
    (verified; cites AWS IAM docs). Factories: `aws_api_faults`, `throttling_service`,
    `timeout_service`.

  - **`linux`** — OOM kill, SIGTERM, ENOSPC filesystem errors. Assumptions:
    `linux:oom-killer-bounded`, `linux:signal-delivery`, `linux:enospc-recoverable` (unverified);
    `linux:fs-rename-atomic` (verified; cites rename(2) POSIX guarantee). Factories:
    `process_faults`, `fs_faults`, `oom_notifier`, `signal_sender`.

  - **`sel4`** — capability revocation, IPC timeout. Assumptions: `sel4:hardware-memory-safety`
    (axiom; Klein et al., SOSP 2009 TCB), `sel4:capability-integrity` (verified; Klein et al.,
    SOSP 2009 § 4 formal proof), `sel4:ipc-liveness` (unverified; not covered by the functional
    correctness proof). Factories: `capability_revocation`, `cap_revocation_notifier`.

  - **`etcd`** — Raft leader change, write conflict, compaction. Assumptions:
    `etcd:quorum-maintained`, `etcd:bounded-leader-election`, `etcd:compaction-bounded`
    (unverified); `etcd:unique-leader` (verified; Ongaro & Ousterhout, USENIX ATC 2014 § 5 Raft
    safety). Factories: `cluster_faults`, `etcd_adversary`.

- **`examples/open_system_composed.py`** — end-to-end multi-environment example: a service
  composed against K8s + AWS + etcd simultaneously, showing a BFS-discovered counter-example
  (unbounded evictions exhaust retry budget) and the full residual proof obligation list.

- **`docs/environments.md`** — reference guide for the environments library: all assumptions,
  factory signatures, composition patterns, simulation usage, and custom assumption injection.

## [0.3.0] - 2026-06-24

### Added — open-system verification

- **`EnvironmentSpec[S]`** — a named contract for an adversarial external component (K8s, AWS, seL4,
  Linux). Each spec carries: `behaviors` (the non-deterministic `Action[S]` objects the environment
  can take), `guarantees` (invariants the environment commits to), and `assumptions` (named proof
  obligations, following seL4's two-layer assurance model: Klein et al., SOSP 2009).

- **`Assumption`** — a named, machine-readable proof obligation with `status ∈ {"axiom", "verified",
  "unverified"}`, an optional `source` citation, and an optional `predicate` for machine-checking.
  Axioms and unverified assumptions surface as residual obligations in `OpenResult`, making hidden
  hypotheses first-class.

- **`check_open(system, *envs)`** — verifies a system against one or more adversarial environments.
  Composes by merging environment behaviors into the system's action set (the BFS explores every
  adversarial move) and environment guarantees into the invariants (qualified as `"<env.name>:<k>"`).
  Returns an `OpenResult` wrapping the underlying `Result` plus all unverified assumptions. With no
  envs, `check_open(m) == check(m)` exactly. Theoretical grounding: Interface Automata (de Alfaro &
  Henzinger, ESEC/FSE 2001) and contract-based design (Benveniste et al., INRIA RR-8147, 2012).

- **`OpenResult[S]`** — the result of `check_open`: `.ok` / `bool()` delegates to the underlying
  `Result`, and `.unverified_assumptions` surfaces residual proof obligations.

- **`AdversarialNode`** — a simulation `BaseNode` that injects Byzantine behavior via a list of
  `(guard, response)` pairs. The first matching guard fires; no match silently drops the message.
  Models external services that return wrong answers, violate protocols, or refuse to respond.
  Grounded in Byzantine fault injection (Castro & Liskov, OSDI 1999).

- **`NetworkModel.mutate`** — a `Callable[[src, dst, payload], object | None]` hook on
  `NetworkModel`. Applied after loss/duplicate decisions, before delivery. `None` return drops the
  message. Models wire-level Byzantine corruption: a component that sends wrong data, not just absent
  data.

- **Worked examples** — `examples/k8s_scheduler.py`: a distributed service verified against K8s pod
  eviction (fragile service fails, resilient service with restart logic passes, residual proof
  obligations printed). `examples/byzantine_service.py`: an `AdversarialNode` that returns wrong
  answers (client without validation fails, with validation passes) and `NetworkModel(mutate=...)` for
  wire-level payload corruption.

- **`docs/open-systems.md`** — a conceptual guide: closed vs. open systems, when to use `check_open`
  vs. `check`, and how to write an `EnvironmentSpec`.

- **`docs/api.md`** — new "Open systems" section documenting `check_open`, `EnvironmentSpec`, and
  `Assumption`.

### Added — verify the *implementation*, not just the design
- **Refinement** (`check_refinement`, `RefinementMonitor`) — check that an observed run of the real
  system refines a model: every transition is a model edge or a stutter (the runtime analog of
  seL4/TLA+ refinement). The oracle that holds real code to a model-checked spec.
- **Deterministic simulation** (`simulate`, `Simulator`, `NetworkModel`, `BaseNode`, `Context`) —
  run real, event-driven node code under a virtual clock and a fault-injecting network (loss /
  duplication / latency-driven reordering), reproducible from a seed. `simulate` runs many seeds with
  invariants + refinement + a convergence goal as the oracle and returns the first failing seed as a
  reproducible `SimFailure`. This is the FoundationDB/TigerBeetle "deterministic simulation testing"
  technique as a pure-Python library -- bug *finding*, not proof.
- **Worked example** (`examples/route_delivery.py`) and a guide (Verifying a distributed system):
  model-check a protocol's design, then put the real code through simulation; the fire-and-forget bug
  is caught with a seed, the per-tick re-push converges and refines the model.

### Added — the textbook (a canon of worked examples)
- **`docs/textbook.md`** — a roadmap mapping the classic concurrency / distributed-systems problems
  (each bounded, ordering- or failure-driven — musil's diet) to the bug each teaches and the feature
  it exercises, so the example suite doubles as documentation and as musil's own coverage matrix.
- **Producer–consumer / bounded buffer** (`examples/producer_consumer.py`) — the check-then-act
  race: two non-atomic producers both pass the "there is room" check and overflow a one-slot buffer;
  the atomic test-and-insert stays within capacity, never deadlocks, and converges.
- **Shared-memory concurrency examples** completing that textbook section: dining philosophers
  (`examples/dining_philosophers.py` — the circular-wait deadlock and the resource-ordering fix),
  readers–writers (`examples/readers_writers.py` — mutual exclusion holds, yet reader-preference
  starves the writer: a liveness/fairness lesson), and bank transfer (`examples/bank_transfer.py` —
  the lock-ordering deadlock plus a conservation invariant).
- **`examples/` is now linted and type-checked** (ruff + pyright strict) in CI and `make check`, so
  the worked examples can't rot.

## [0.1.0] - 2026-06-21

Initial release.

### Added
- **Core checker** (`check`) — breadth-first sweep of every reachable state for the first invariant
  violation or deadlock, with the shortest counterexample trace. States are immutable, hashable
  values (frozen dataclasses); actions are pure guarded transitions.
- **Concurrency by interleaving** — modelling several actors is just handing `check` all their
  actions; every interleaving is explored.
- **Liveness** (`check_liveness`) — proves `<>P` ("eventually P") and, with `everywhere=True`,
  `[]<>P` ("always eventually P" / convergence). Tarjan SCC + lasso counterexamples. **Weak** fairness
  via `fair=[...]` and **strong** fairness via `fair_strong=[...]`.
- **Composition** (`compose`) — the interleaved product of independent component models, lifting each
  component's invariants (name-qualified) and supporting joint invariants over the composite.
- **Channel kit** (`channel_actions`, `send`) — model a message channel as a building block:
  reliable / lossy / duplicating, unordered so reordering is explored for free.
- **Zero-drift FSM bridge** (`transition_actions`, `status_field_actions`, `terminal_states`,
  `declared_states`) — build a model straight from an allowed-transitions table so it can't diverge
  from the code.
- **Conformance** (`generate_traces`, `replay`) — generate traces from the model and replay them
  against the real implementation to check it refines the model.
- **Graph export** (`to_dot`) — Graphviz DOT of the reachable state graph, with counterexample
  highlighting; plus `explore` for the raw reachable graph.
- **CLI** (`python -m musil <model.py>`) — check a model module from the command line.
- PEP 695 generics, `py.typed`, zero runtime dependencies, Python 3.12+.

### Known limitations
- Explicit-state: for bounded models (use the `max_states` cap; results flag `truncated`).
- No partial-order reduction yet; heavy interleaving can be expensive.
- Liveness is fairness-based, not full LTL (`<>P` / `[]<>P` under weak/strong fairness).
