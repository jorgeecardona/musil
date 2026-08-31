# Changelog

All notable changes to musil are documented here. Versioning is [SemVer](https://semver.org/).

## [Unreleased]

### Added — `musil.history.with_last_action`: temporal properties over the action sequence

- `with_last_action(model)` augments each state to `LastAction(state, action)` — the original state plus the
  name of the action that produced it (`None` at an initial state) — so `check_ltl` / `check_liveness` can
  express properties over WHICH action was taken: "every `request` is eventually followed by a `respond`" as
  `G(action_taken('request') -> F action_taken('respond'))`. A state-only predicate cannot say "`request` was
  just taken", and a safety-only edge invariant cannot make a liveness claim across a run. Every model field
  is lifted faithfully (initial states get `action=None`; actions keep their `name`/`fair` tag and record
  themselves on apply; invariants/terminal/edge_invariants/footprint read `.state`; `actions_fn` is lifted).
  `action_taken(name)` is the "last action was `name`" predicate. Pure stdlib.
- Corpus pins a request/respond protocol: `G(respond -> F reset)` holds, `G(request -> F respond)` fails (the
  timeout loop can starve a response without fairness), and the safety verdict is preserved by the
  augmentation. `LTL_NOTES.md` records that this is the substrate for the deferred action-fairness engine
  (the weak/strong premises become plain LTL over `action_taken`/`enabled` atoms on the augmented model).

### Fixed — probabilistic weights: reject a negative weight instead of returning a bogus probability

- A negative `weight` silently produced a wrong answer: the weights are normalised into a probability
  distribution, so a negative one yields a negative or `>1` "probability", or a spurious `0` when the weights
  sum to zero (e.g. `reach_probability(..., weight=w)` returned `0` with no error). Every entry point that
  takes a `weight` — `reach_probability`, `reach_probability_mdp`, `expected_reward`, `expected_reward_mdp`,
  `long_run_probability` — now raises `ValueError` on a negative weight, via a shared `_weight_of` guard at
  the single normalization point. Corpus pins that all five reject a negative weight.

### Added — `examples/availability.py`: the steady-state / until / MDP-cost probabilistic answers, worked

- A worked example for the three most recently shipped probabilistic capabilities, which had no example
  (closing the "shipped features go unadopted" gap directly): `long_run_probability` (steady-state
  availability of a service that cycles HEALTHY/DEGRADED/FAILED forever — `π(healthy) = 4/7`),
  `reach_probability(..., avoid=...)` (the until-probability of FAILING before recovering — 1/2, vs plain
  reachability 1), and `expected_reward_mdp` min/max (a STAGED vs DIRECT recovery strategy — min cost 2, max
  3). Every answer is an exact `Fraction` matching a hand-computed closed form; the example asserts them and a
  subprocess test pins them. `docs/examples/availability.md` renders the scenario. No new library code.

### Added — constrained (until) reachability: `avoid=` on `reach_probability` / `reach_probability_mdp`

- The exact probability of the until property `P(¬avoid U target)` — reaching the target WITHOUT first
  entering an `avoid` state — on both the DTMC (`reach_probability`) and MDP (`reach_probability_mdp`, min/max)
  functions, unbounded and `steps=k`. Reuses the existing 0-sink mechanism: an `avoid` state that is not
  itself a target becomes an absorbing failure (value 0), which `_dtmc_values` / `_bounded_values` / `_s0_min`
  already resolve correctly; `target` takes precedence. Corpus pins a DTMC where `avoid` drops reachability
  from 1 to 1/2 (a state that reaches the target a.s. by bouncing, but only directly with probability 1/2
  while avoiding a failure state) and an MDP where `avoid` separates the schedulers (min 1 -> 1/2, max stays
  1). No dependency.

### Added — `long_run_probability`: exact DTMC long-run / steady-state fraction of time

- The exact fraction of time a DTMC spends in a target set in the limit (PRISM's steady-state / S operator), a
  `Fraction`. A finite DTMC is absorbed almost surely into a bottom SCC (BSCC); inside each BSCC the long-run
  fraction of time in a state is its stationary probability, so the answer is `sum_B reach(B) * sum_{s in B,
  target(s)} pi_B(s)`. Reuses the proven `tarjan` for the BSCC decomposition and the exact `_dtmc_values` for
  reachability to each BSCC; the stationary distribution is an exact rational solve (`_stationary`: `pi P =
  pi`, `sum pi = 1`, Gauss-Jordan). Equals the time average even for a PERIODIC BSCC (the Cesàro limit, where
  `P^n` does not converge); transient states carry zero long-run measure; a deadlock/absorbing state is its
  own BSCC. Corpus pins the periodic 2-cycle (`1/2`), a biased chain (`1/3`), and a transient split into two
  absorbing BSCCs (`1/2`; `1` for the whole absorbing set). No dependency.

### Added — `expected_reward_mdp(..., optimize="max")`: MDP maximal expected reward (stochastic longest path)

- The maximal expected accumulated cost to first reach the target over all schedulers, exact over the
  rationals. Finite only when EVERY scheduler is proper (else a scheduler loops away from the target and the
  max is infinite), so it guards on MIN reachability 1 from the initial state — reusing the existing `_s0_min`
  + minimizing `_reach_policy_iteration` — which implies every reachable state is proper. Any policy is then a
  proper seed, and maximizing policy iteration (each switch strictly raises a bounded, monotone expected cost)
  converges to the optimum (Bertsekas & Tsitsiklis SSP, all-proper case), sharing the min path's exact
  evaluation. Raises when the guard fails (some scheduler avoids the target with positive probability, max is
  infinite) or `optimize` is not `"min"`/`"max"`. Corpus pins a fast-vs-slow MDP (`min = 1`, `max = 2` steps)
  and the infinite guard (a self-loop `stall` move drops min reachability below 1, so max raises, min stays 1).
- `PROBABILISTIC_NOTES.md` moves MDP max expected reward from Deferred to Shipped; only zero/negative-cost SSP
  and probabilistic-LTL/steady-state remain deferred.

### Added — the composed-components scaling benchmark + the symmetry recipe (#37)

- `examples/cosim_master_scaling.py`: a generic co-simulation master over N interchangeable components (each
  taking up to `k` independent micro-steps per macro step, with rollback) — the named partial-order-reduction
  benchmark, run as a MEASUREMENT. The curve (`k=3`, n=2..5): full interleaving `(k+1)ⁿ` = 16, 64, 256, 1024;
  under sorting symmetry `C(n+k, n)` = 10, 20, 35, 56 (up to 18.3× at n=5). The full search crosses the
  default `max_states=1_000_000` around n=10; the symmetric search is still 286 states there. The measured
  answer: for anonymous interchangeable components, `canonical_by_sorting` — not POR — makes the workload
  scale, which is why POR stays deferred behind this curve (`REDUCTION_NOTES.md`). No new library code.
- `docs/examples/cosim_scaling.md`: the "interchangeable components in a composed model" `canonicalize=`
  recipe as a documented lever (build the slice accessor pair, hand it to `canonical_by_sorting`, and validate
  with `symmetry_reduction_sound` first), with the curve and the soundness caveats. The example's own asserts
  pin the closed-form counts and run `symmetry_reduction_sound` on each instance; `tests/test_example_cosim_scaling.py`
  runs it as a subprocess and pins the published curve.

### Fixed — `check_ltl`: refuse fairness on the general engine instead of silently dropping it

- `fair` / `fair_strong` are honoured only for the reducible LTL forms (F / GF / G(a -> F b)), which route
  through `check_liveness`. The general Büchi engine (Until / Release / Next / nesting) did not compose
  fairness and silently IGNORED a `fair` / `fair_strong` argument — returning a verdict, and possibly a
  counterexample lasso, that a fair scheduler would exclude. `check_ltl` now RAISES `NotImplementedError`
  when a non-empty `fair` / `fair_strong` is passed with an irreducible formula, keeping the surface sound;
  an empty `fair=()` is no constraint and still runs. The liveness patterns are unaffected (their formulas
  always reduce). `LTL_NOTES.md` records the deferral: composing fairness in the engine needs action-labelled
  atoms in the product (the premise `(GF enabled_a -> GF taken_a) -> φ` is over action occurrences), the next
  LTL increment.

### Changed — BFS-loop unification (roadmap 1b): share successors on the edge-invariant path

- On the edge-invariant path `check` and `check_all` computed every successor TWICE per state: once for the
  edge-invariant scan, again inside `_expand`. They now compute the `(name, canon(next))` list ONCE and feed
  it to a new `_extend_frontier` primitive that does the frontier bookkeeping + `max_states` truncation from an
  already-computed successor list. Fewer applies on that path; verdict, trace, and truncation are identical
  (guarded by the existing edge-invariant + `check_of` differential cases and a new corpus case pinning
  truncation-under-edge-invariants and same-reachable-set-as-`explore`). The soundness-critical successor
  computation stays the single `_successors`.
- `src/musil/BFS_UNIFICATION_NOTES.md` records the (1b) design decision: `check`/`check_all` are unified at the
  primitive level (`_successors`, `_seed_frontier`, `_expand`, `_extend_frontier`); `explore` shares
  `_successors` but keeps its own edge-recording loop; `profile` stays inlined so it can time each primitive.
  A single driver loop for all four is deliberately NOT done: it would regress `check`'s check-before-expand
  early-exit or delete `profile`'s per-primitive measurement.

### Added — `musil.citations`: model references must not dangle (#34)

- A good practice is for production code to CITE the model that justifies a non-obvious design
  (`... — test_mesh_membership_musil`); it fails silently when the pointer rots (code cites a model file that
  no longer exists anywhere). `find_citations(source) -> list[Citation]` locates the references with a regex
  (so it sees comments and prose, not only identifiers), and `dangling_citations(source, known)` reports the
  ones whose model name is not in `known` — typically `known_models(test_tree)`, the stems of the
  `test_*_musil.py` files that exist. Pure stdlib (`re` + `pathlib`); never imports or runs the scanned code.
  The reference shape (`test_*_musil`) is the default; `pattern=` overrides it.
- `python -m musil citations <path>... [--pattern P]` runs it as a gate: it resolves every citation under the
  given paths against the model files that exist there and exits 1 iff one dangles (0 when all resolve),
  printing `file:line: dangling model citation: <name>`. A companion to `musil doctor` on the same CLI.
- `tests/test_citations.py` pins finding, word-boundary handling, dangling-vs-known, filesystem resolution,
  and a custom pattern; `tests/test_cli.py` pins the gate's exit codes (1 on a dangling ref, 0 when clean).

### Added — `examples/distributed_kit.py`: the reconciler + fault kit, worked end to end

- A worked example of the distributed-systems builders (`reconciler`, `crash_actions`) that most models
  reach for, addressing the recurring "shipped features go unadopted" finding directly. Two verifiable
  halves: (1) a controller whose `[]<>converged` HOLDS under a fair reconcile even as an unfair `glitch`
  fault keeps resetting it, and FAILS with `fair=()` (the fault can starve reconcile forever) — showing the
  fair-ours / unfair-faults discipline is what carries convergence; (2) a 3-node cluster whose quorum
  invariant survives a crash `budget=1` but breaks at `budget=2`. The example asserts both verdicts; a
  subprocess test pins them. No new library code.

### Added — `musil.doctor.scan`: spot hand-rolled patterns a shipped API already covers (#36)

- `scan(source) -> list[Finding]` reads Python source with the standard-library `ast` (dependency-free, and
  it never imports or runs the code) and returns advisory `Finding`s — file positions plus the API to reach
  for — closing the loop on the recurring finding that shipped features go unadopted. Detected today:
  `assert X.ok, <msg>` -> `assert_ok(X)` (the message is the tell that distinguishes musil's idiom from a
  bare truthiness assert, e.g. `requests`' `response.ok`); `assert not X.ok` -> `assert_violates(X, ...)`;
  and `[s.action for s in X.trace ...]` -> `X.action_names`. Advisory, not a gate.
- `tests/test_doctor.py` pins the matchers on known snippets (source -> expected finding), including that a
  bare `assert x.ok` and code already using the shipped APIs are left alone.

### Added — `musil doctor <path>` CLI + a `musil` console command

- `python -m musil doctor <path>` scans a file or directory (recursively) with `musil.doctor.scan` and
  prints `file:line:col: pattern: suggestion`; unreadable / un-parseable files are skipped and it always
  exits 0 (advisory, not a gate). This is the runnable front end for the `scan` core — the thing consumers
  actually invoke — completing #36's CLI half.
- The package now installs a `musil` console entry point (`[project.scripts]`), so `musil doctor <path>`
  works directly, and the existing `python -m musil <model.py> [--dot]` model-check path is unchanged (the
  `doctor` subcommand is a backward-compatible addition). `tests/test_cli.py` covers both paths.

### Added — `portfolio_coverage` + `assert_covers`: suite-level coverage of a declared table (#35)

- `portfolio_coverage(models_or_graphs, get=, declared=)` answers the question a single-model `coverage`
  cannot: how much of a declared external state machine does the WHOLE portfolio exercise? It reads the
  transitions of a state FIELD across each edge (`get(before) -> get(after)`, so action naming is
  irrelevant), unions them across every model, and diffs against the `declared` table — returning a
  `PortfolioCoverage` with covered / dead / undeclared edges, covered / dead field values, and an exact
  `ratio` (`Fraction`). A `Graph` is used as-is; a `Model` is explored.
- `assert_covers(portfolio, declared, get=, ratio=, blind_spots=)` is the ratchet gate that fixes the
  numerator-only "N transitions covered" test which let one suite rot 67% -> 56% while staying green. It
  asserts: (1) no undeclared transition (the portfolio never exercises an edge the table forbids); (2) the
  dead edges are EXACTLY the named `blind_spots` (a new dead edge is a regression; a covered blind spot must
  be removed — the set can only shrink); (3) the coverage ratio meets the floor.
- Corpus pins a two-model portfolio over a 4-edge table: the union covers all four (ratio 1), one model
  alone covers half, and the gate rejects both a new unacknowledged dead edge and an undeclared transition.

### Added — `musil.reconciler`: the controller/reconciler shape as a builder (#23)

- `reconciler(get_desired=, get_actual=, set_actual=)` returns `(converged, reconcile)` for the single most
  common shape in modern infrastructure (operators, sync engines, cache maintainers): a `desired` field the
  environment sets, an `actual` field the controller drives toward it, goal `[]<>converged`. `converged` is
  `actual == desired` (feed to `check_liveness(everywhere=True)`); `reconcile` is a fair `Action` (tagged
  `fair="weak"`) that sets `actual` to `desired` while they differ — the "ours" side of the fair-ours /
  unfair-faults discipline, so a liveness proof may assume the controller keeps reconciling but not that a
  fault heals itself. Composes with the fault factories (`crash_actions`, channel loss) as unfair actions or
  `check_open` environments. Generic over both the state and the value type.
- Corpus pins a reconciler with a competing UNFAIR `idle` self-loop: `[]<>converged` HOLDS because reconcile
  is weak-fair by construction, and FAILS with `fair=()` (idle can starve reconcile forever) — showing the
  fair tag is exactly what carries convergence. The chosen-design / negative-control TEST HARNESS the issue
  also mentions is a larger, separate piece and is deferred.

### Added — richer transition builders: `effect` / `also`, and `replicated_transition_actions` (#26)

- `transition_actions` gains two keyword arguments: `effect(state, src, dst)` runs after the status change
  and returns the state with side effects on OTHER fields applied (so a transition is not limited to
  swapping the status field), and `also(state)` is an extra guard ANDed with "currently in `src`" for a
  cross-cutting precondition the table itself does not encode. Backward-compatible (both default to `None`).
- `replicated_transition_actions(table, instances, get=, set_status=, effect=, also=)` runs N copies of one
  transition table — one machine per instance — over a FLAT state, for a system of interchangeable entities
  (entries, replicas, jobs) that all obey the same lifecycle. `instances` is an `int` N or an iterable of
  keys; the projections are per-instance (`get(s, key)` / `set_status(s, key, dst)` / `effect(s, key, src,
  dst)` / `also(s, key)`). Unlike `compose` (which forces a `Composite` tuple state), the state stays a flat
  dataclass, so cross-instance invariants (`a + b == 0`) remain expressible.
- Retires the hand-written triple loop + `_ENTRY_FIELDS` / per-instance index helpers that multi-entity
  workflow models write while citing the zero-drift docs. Corpus pins a two-entry ledger: 2 entries × 2
  edges = 4 actions, 9 reachable states, and the `effect` keeps `balance == count of posted entries` (a
  cross-instance invariant). Gap #4 of the issue (the illegal-firing ghost flag) is already covered by the
  edge invariants added earlier.
- `assert_covers_table(model, table, get=)` checks the zero-drift claim mechanically, replacing the
  hand-rolled action-name test: over the reachable space, every step that changes the status must go to a
  `dst` declared in `table[src]`, so the model can never make a transition the table forbids. It raises
  `AssertionError` listing any undeclared `src -> dst` found. It checks CONFORMANCE (no forbidden
  transition), not completeness — a declared edge may be legitimately unreachable or held off by an `also`
  guard, so "every table edge is exercised" is left to the caller (`declared_states` / `terminal_states`
  help). Corpus pins that a table-built ledger conforms and that a hand-written `draft -> closed` skip is
  caught.

### Added — `musil.faults`: explicit-state crash/revive and partition/heal faults (#29)

- New module `musil.faults` with two action factories for the explicit-state path (`check` / `explore` /
  `check_open`) where most models live — retiring the byte-identical per-node fault edges distributed models
  hand-write. Same lens style (`get`/`put`) as `musil.channels`.
- `crash_actions(nodes, get_up=, set_up=, budget=, revive=)` builds crash (and optional revive) `Action`s
  over a node-liveness lens. `budget` bounds the number of SIMULTANEOUS failures (a crash fires only when
  fewer than `budget` nodes are already down); `revive=True` adds heal edges for reconvergence testing.
- `partition_actions(splits, get_reach=, set_reach=, healed=)` builds partition/heal `Action`s over a
  reachability lens: each caller-supplied split installs from the HEALED state (partitions do not stack),
  and a single heal restores `healed` — the heal-able network-partition fault.
- Corpus pins a 3-node quorum mesh for each: `crash_actions` with `budget=1` holds quorum (≥2 of 3 up) in 4
  states and `budget=2` drops below it via two `fault:crash:*` edges; `partition_actions` with a `{0}|{1,2}`
  split holds quorum in 2 states and an all-singletons split breaks it via the `fault:partition:0` edge.
- Note: the issue referenced a `cohort_faults` (0.28) precedent, but no such helper exists in musil — both
  factories are designed fresh against the `channels` factory convention (`partition_actions` adds an
  explicit `healed=` for the full-reachability configuration).

### Added — fairness by action tag + fair-name validation (#27)

- `Action(..., fair="weak" | "strong" | None)` — an action can carry its own fairness. When
  `check_liveness` is called with no explicit `fair=` / `fair_strong=` tuple (now defaulting to `None`), it
  DERIVES the weak/strong sets from these tags, so the fair-ours / unfair-faults split lives on the action
  that knows what it is, instead of a parallel name list kept in sync by hand.
- **Soundness fix:** an explicit `fair` / `fair_strong` name that matches no action now raises `ValueError`
  instead of being silently ignored. A silent no-match fails in the unsound direction (an action that should
  be fair is treated as unfair, or a `startswith`-style filter accidentally grants fairness and a real
  violation disappears). Tags and validation apply to a static `actions` list; with `actions_fn` names are
  passed explicitly and used unchecked. Backward-compatible: models without tags and callers passing valid
  names are unchanged (all 359 prior tests pass).
- Corpus pins that deriving from a `fair="strong"` tag equals passing the name explicitly, that an explicit
  empty set overrides the tags (no fairness), and that a bad name raises.
- The tags flow through the `musil.patterns` sugar (`eventually` / `recurs` / `responds`) and `check_ltl`
  too: their `fair` / `fair_strong` now default to `None` (forwarded to `check_liveness`), so a tagged model
  gets its fairness whether you call `check_liveness` directly or via a pattern.

### Added — edge (transition) invariants: predicates over `(before, action, after)` (#25)

- `Model.edge_invariants={name: fn(before, action_name, after) -> bool | str}` — invariants about the STEP,
  not the state, for the case where the bad state is legitimately reachable but a particular EDGE into it is
  illegal (TLA+'s action formula). Checked on every explored edge by `check` and `check_of`; the first
  violation returns a `Result` with `kind="edge-invariant"`, the broken name in `invariant`, and the
  offending transition as the last step of the shortest trace. Off by default (empty), and it recomputes
  successors only when present, so models without edge invariants pay nothing.
- `never(action, when=...)` — the direct "forbid this transition" edge invariant, replacing the ghost-flag
  pattern (a state field set purely to turn "an illegal action fired" into a state predicate, which doubles
  the state space it lives in).
- Corpus pins a document lifecycle where `published` is legitimately reachable (so a state-only `check` is
  green) yet a `force_publish` edge reaches it illegally — the edge invariant catches exactly that edge, and
  `check_of` returns the identical verdict and trace.
- `check_all` (the all-violations audit) now also checks edge invariants, bucketed in their own namespace so
  an edge and a state invariant of the same name never collide; it reports state and edge violations together
  in one pass. (It previously ignored them silently — an unsound-direction gap in an audit tool.)

### Added — `check_liveness_of`: liveness over a pre-built graph (#31)

- `check_liveness_of(graph, goal=..., ...)` runs the liveness analysis over an already-explored `Graph`
  instead of re-exploring — the graph-first counterpart to `check_liveness`, same properties/verdict/lasso.
  `check_liveness` was refactored to be exactly `check_liveness_of(explore(model, max_states=...), ...)`, so
  there is a single analysis path (no divergence risk) and the graph can be shared with `check_of` /
  `coverage_of` / `invariant_coverage_of`. Corpus pins that the two entries give the identical
  `LivenessResult` on a passing case and on a strong-fairness sub-SCC counterexample.
- With this, `check_of` + `check_liveness_of` cover the safety and liveness halves of #31; `fixed_points_of`
  remains open pending the per-initial-state semantics decision (`fixed_points` explores each initial
  separately, so a single merged graph would give a narrower answer).

### Added — `check_of`: the safety check over a pre-built graph (#31, partial)

- `check_of(graph, model)` runs the safety verdict over an already-explored `Graph` instead of re-exploring
  — the graph-first counterpart to `check`, as `coverage_of` is to `coverage` — so several analyses
  (coverage, safety, ...) can share one `explore`. Returns the same `Result`: the first invariant violation
  or deadlock in breadth-first order (shortest trace), else OK.
- A differential test in the corpus pins that `check_of(explore(m), m)` gives the SAME verdict AND the same
  shortest trace as `check(m)` on every corpus model — the guard against the two code paths diverging (they
  agree exactly today, trace included). Deadlock detection needs a complete graph: on a truncated one a
  cut-off frontier state looks like a sink, so `check_of` reports invariant violations there but not
  deadlocks, and a clean result carries `truncated=True`.
- `check_liveness_of` and `fixed_points_of` (the rest of #31) are follow-ups: `check_liveness` factors
  cleanly (it already explores-then-analyses), while `fixed_points` explores each initial state separately,
  so a single-graph variant has a narrower per-initial semantics to settle first.

### Added — negative-side assertion helpers: `assert_violates`, `.action_names`, `.witness` (#32)

- `assert_violates(result, kind=..., invariant=..., via=[...], where=lambda s: ...)` — the red-side
  counterpart to `assert_ok`: asserts a check FOUND a violation, optionally pinning the verdict kind, the
  broken invariant, actions that must appear in the counterexample, and a predicate on the offending state,
  rendering the full counterexample on any mismatch. Works on `Result` and `LivenessResult` alike.
- `Result.action_names` / `LivenessResult.action_names` — the action names along the counterexample,
  excluding the synthetic `<init>` step (for `LivenessResult`, the stem then the cycle). `Result.witness` /
  `LivenessResult.witness` — the offending state (the last state of the trace / stem). These replace the
  hand-rolled `[step.action for step in result.trace ...]` and `result.trace[-1].state` idioms.

### Changed — `assert_ok` rejects a truncated green by default (`truncated="fail"`)

- `assert_ok(result)` now FAILS when the result passed but the sweep TRUNCATED at `max_states` — a truncated
  green proves nothing about the unexplored part, so treating it as a proof was a quiet soundness hole in
  test suites. Pass `truncated="ok"` to accept an inconclusive pass. This is a behaviour change: a test that
  asserted `assert_ok` on a truncated result now fails (correctly); raise `max_states` or opt out
  explicitly. Consistent with musil's exact-only stance (a clean `check` is a proof, a truncated one is not).

### Added — witness API: `path_to`, `witness`, `states_where` (positive witnesses over a graph)

- musil could produce counterexamples (paths to a *bad* state) but had no first-class way to get a positive
  WITNESS — a path to a *good* state. `reaches` answers "can it get there?" as a yes/no over the whole
  reachable set; these return the concrete path (GitLab #30):
  - `path_to(graph, state)` — the shortest path (a `Step` tuple, render with `format_trace`) from an initial
    state to a specific reachable `state`, or `None` if unreachable.
  - `witness(graph, predicate)` — the shortest path to SOME reachable state satisfying `predicate`, or
    `None` (the concrete-path counterpart to `reaches`).
  - `states_where(graph, predicate)` — the reachable states satisfying `predicate`, in exploration order
    (`solution_cardinality` counts these; this returns them).
- All three operate on a pre-built `Graph`, via a shared forward-BFS shortest-path helper, so no
  re-exploration. Corpus pins the exact path lengths on the counter model and the `None` cases.

### Fixed — `check_liveness`: strong fairness missed sub-SCC counterexamples (soundness)

- `check_liveness(..., fair_strong=(...))` could return `ok=True` when a fair counterexample existed — a
  false OK, the unsound direction. Fairness was judged on the MAXIMAL SCC: a strongly-fair action enabled
  anywhere in the SCC but never taken there ruled the whole SCC out, even when a cycle confined to a
  *sub-SCC* never enables that action and so carries no fairness obligation. `_find_fair_scc` now applies
  the standard Emerson-Lei refinement — remove the states that enable an unsatisfied strongly-fair action
  and re-decompose the remainder, recursing to a fixpoint — so a fair cycle in a sub-SCC is found.
- Regression pinned in the corpus (issue #22): a model whose maximal SCC contains a strongly-fair action
  enabled only at one state, with a sub-cycle that avoids it, now correctly reports the fair counterexample
  (cycle confined to the sub-SCC); a companion model where the fair action is enabled throughout the only
  cycle still correctly reports the property holds (the fix does not over-report). Weak fairness is
  unchanged (enabled-everywhere persists under any subset, so it needs no refinement).

### Added — `examples/coverage_vacuity.py`: when a green check is meaningless

- A worked example of `coverage` / `invariant_coverage` (GitLab #2 item 1, "cheapest, highest signal"): a
  tiny account passes `check` cleanly, yet `coverage` flags a dead action (`thaw`, guarded on a status
  nothing sets) and `invariant_coverage` flags a vacuously-true invariant (`status-known`, which no action
  can break) while confirming `non-negative-balance` is genuinely load-bearing (the withdraw guard protects
  it). Shows that OK means "no invariant broke," not "the behaviour was exercised" or "the invariants caught
  anything." Subprocess test pins the reports; the example asserts them itself. Generic account domain, no
  new library code.

### Added — `examples/ltl_properties.py`: the LTL layer, worked end to end

- The first worked example of `check_ltl`: a traffic light with six temporal properties that hold (safety
  `G known`, `F green`, recurrence `G F red`, response `G(yellow -> F red)`, `X green`, `known U green`),
  spanning the reducible fragment and the general Büchi engine (`Next`, `Until`). The last property,
  `F G green` ("eventually green forever"), is FALSE and returns a counterexample as an infinite run — a
  lasso with the `--- loops forever ---` marker showing the light never stabilises. A subprocess test pins
  the verdicts and the marker; the example asserts them itself. Generic traffic-light domain, no new library
  code.

### Added — `examples/lossy_retry.py`: the probabilistic layer, worked end to end

- The first worked example of `musil.probabilistic`: a message over a lossy link (each attempt delivers
  with probability 1/2, else retries). It shows `reach_probability` (eventual delivery = 1), the bounded
  `reach_probability(..., steps=k)` geometric law `1-(1/2)^k`, `expected_reward` (expected attempts `1/p =
  2`), and `expected_reward_mdp` (when the sender may pick a fast or careful link, the minimal expected cost
  over all strategies, `2`, with the fast link chosen) — all as exact `fractions.Fraction`. A subprocess
  test pins the printed closed forms, and the example asserts them itself. Generic networking domain, no
  new library code.

### Added — LTL counterexamples mark where the infinite run loops

- `Result` gains a `loop: int | None` field: for an infinite-run (LTL lasso) counterexample it is the index
  in `trace` where the cycle begins — the state reached, then repeated forever — and `None` for a finite
  (invariant/deadlock) counterexample. `check_ltl`'s general engine now sets it (`accepting_lasso` returns
  the stem length alongside the lasso), and `format_trace` emits a `--- loops forever ---` marker after that
  state (matching the existing `LivenessResult` rendering), so a liveness counterexample shows which suffix
  repeats. `Result.__str__` also renders a proper `LTL VIOLATED: <formula>` header for `kind="ltl"`.
- The field is defaulted, so every existing `Result` construction is unchanged. Corpus pins that the loop
  index is in range and that the cycle closes back to the marked entry state.

### Fixed — `musil.ltl`: document the general-engine counterexample trace (and pin it)

- The `check_ltl` docstring and the docs LTL section claimed the general Büchi engine returns "no
  counterexample trace yet" / that out-of-fragment formulas "raise `NotImplementedError`". Both were stale:
  the engine has for a while returned a real counterexample — the accepting lasso of the `Not(formula)`
  automaton mapped back to model states (`<init> -> stem -> cycle`) — as `Result.trace`, and out-of-fragment
  formulas are decided, not rejected. Corrected the docstring and `docs/api.md`.
- Corpus now pins the guarantee: for a failing out-of-fragment formula (`Next(red)` on the traffic light),
  `check_ltl` returns a non-empty trace that is a GENUINE run of the model — it starts at the initial state
  and every consecutive pair is a real model edge. So the counterexample can never silently regress to empty
  or to a non-run.

### Changed — `musil.patterns`: the liveness patterns are now sugar over `check_ltl`

- `eventually`, `recurs`, and `responds` now build the corresponding LTL formula (`Eventually(p)`,
  `Always(Eventually(p))`, `Always(Implies(trigger, Eventually(response)))`) and call `check_ltl`, instead
  of calling `check_liveness` directly. `check_ltl` already owns the one reduction of that temporal fragment
  onto `check_liveness` (with the same `fair` / `fair_strong` handling), so the lowering now lives in a
  single place — fix or extend it there and every pattern follows — and a pattern is by construction the
  same verdict as its LTL formula. Behaviour and return types are unchanged (each still returns the same
  `LivenessResult`); the existing pattern tests pass untouched, and a corpus entry pins the
  pattern-vs-`check_ltl` agreement on both a property that holds and one that does not.
- The two safety patterns (`always`, `absent`) stay direct `check` calls: `G(state)` is just an invariant,
  and they expose `canonicalize` / `key` that `check_ltl`'s safety reduction does not forward, so routing
  them through it would drop those options for no gain. This is the "patterns re-expressed as sugar over
  `check_ltl`" roadmap item, done where it is lossless.

### Added — `musil.probabilistic`: MDP min expected reward (stochastic shortest path)

- `expected_reward_mdp(model, target, moves=..., cost=...)` returns the exact MINIMAL expected accumulated
  cost to reach `target` over all schedulers of an MDP (default unit cost = minimal expected steps).
- The normally-hard piece, a *proper* initial policy for policy iteration, comes for free: the
  max-reachability-optimal policy reaches the target almost surely from every state whose max reachability is
  1 (a convex combination of values `<= 1` equal to 1 forces every successor to 1), so it is proper there
  and seeds the iteration. The iteration minimises expected cost over the moves whose successors are all
  proper, each evaluation an exact rational solve of `E(s) = cost(s) + sum_s' P(s, s') E(s')`. Strict
  improvement keeps the policy proper (an improper policy has infinite cost) and terminates at the optimum
  (Bertsekas & Tsitsiklis SSP).
- Costs must be positive (default unit); it raises `ValueError` when no scheduler reaches the target almost
  surely from the initial state (min expected cost infinite). MAX expected cost and zero/negative-cost
  cycles are deferred (reasons in `PROBABILISTIC_NOTES.md`). Refactored the reach policy iteration into a
  shared `_reach_policy_iteration` that returns the optimal values AND policy (the SSP seed); guarded by the
  existing MDP reachability corpus.
- Corpus pins the retry-until-success minimal expected attempts `1/p` (a slower sure alternative does not
  lower it), plus tests for the cheaper-route choice, the safe-move restriction (avoid a non-reaching
  branch), the infinite-cost guard, and ignoring an improper self-loop.

### Added — `musil.probabilistic`: DTMC expected reward (`expected_reward`)

- `expected_reward(model, target, cost=...)` returns the exact expected accumulated cost to first reach
  `target` in a DTMC; with the default unit `cost` it is the expected number of steps. Solves `E(target)=0`
  and `E(s) = sum_s' P(s, s') (cost + E(s'))` over the rationals (no floating point).
- The expectation is finite only when the target is reached ALMOST SURELY, so it guards on
  `reach_probability == 1` from the initial state and raises `ValueError` otherwise (infinite expectation).
  That guard is what makes the `(I - P)` system on the non-target states non-singular: every explored state
  is init-reachable, and if init reaches the target a.s. then so does every non-target state.
- Corpus pins two known closed forms: the fair-walk absorption time `E = i(N-i)` and the geometric mean
  `1/p` for a coin loop. MDP expected reward (the stochastic shortest/longest path problem) is deferred with
  the reasons in `PROBABILISTIC_NOTES.md` (MAX is infinite unless all schedulers are proper; MIN needs a
  proper initial policy and zero-cost-cycle care).

### Added — `musil.probabilistic`: step-bounded reachability (`steps=k`)

- Both `reach_probability` and `reach_probability_mdp` now take an optional `steps=k`: the exact
  probability of reaching `target` WITHIN `k` transitions (the unbounded probability is still the default,
  `steps=None`). Computed by a finite backward induction (`_bounded_values`): `V_0` is the indicator of the
  target, `V_i(s) = opt_move sum_s' P(s, s') V_{i-1}(s')`. No fixed point, so it is exact by construction
  and needs no `S0` precomputation — a bounded horizon cannot stall. `steps=0` is the indicator of the
  target; a DTMC is the single-move case (the per-step optimisation is over one value). Negative `steps`
  raises `ValueError`.
- Corpus pins the geometric law: for a fair coin loop (win with prob 1/2 each step, else retry),
  `reach_probability(..., steps=k) == 1 - (1/2)^k`, exactly, for every `k`.

### Added — `musil.probabilistic`: MDP min-reachability (exact, via S0min + policy iteration)

- `reach_probability_mdp(..., optimize="min")` now returns the MINIMAL probability of eventually reaching
  `target` over all schedulers (it previously raised `NotImplementedError`). Same exact policy iteration as
  the max case, minimizing, with one precomputation: `_s0_min` finds the states from which a scheduler can
  avoid the target forever (the greatest set of non-target states in which every state has a move whose
  support stays inside the set, by iterative removal) and pins them to probability 0.
- That precomputation is exactly what makes min exact: without it, min policy iteration stalls on a
  self-loop (or a loop through a non-target end component) whose move-value equals its current value, so the
  strict-improvement step never lowers it to the true 0. With `S0min` pinned, no set of the remaining
  states can be closed under any policy, so every policy is proper and minimizing policy iteration converges
  to the unique exact `xmin`. No maximal-end-component *collapse* is needed — `_dtmc_values` already zeroes
  unknowns a fixed policy cannot route to the target. See `PROBABILISTIC_NOTES.md`.
- Corpus pins three known verdicts: the two-gamble MDP (`xmin = 1/2`, the worse coin, vs `xmax = 2/3`), a
  self-loop (`xmin = 0`, `xmax = 1`), and a two-state non-target end component (`xmin = 0`) — the case
  `_s0_min` exists for.

### Added — `musil.probabilistic`: MDP max-reachability (exact policy iteration)

- `reach_probability_mdp(model, target, moves=..., optimize="max")` adds NONDETERMINISTIC choice on top of
  the DTMC layer: a caller-supplied `moves(state, enabled_actions)` partitions each state's enabled actions
  into the moves a scheduler picks between, and the actions within a move form one probability distribution
  (via `weight`). It returns the MAXIMAL probability of eventually reaching `target` over all schedulers.
- Solved EXACTLY by policy iteration: each policy's value is an exact DTMC solve (`_dtmc_values`, now shared
  with `reach_probability`), then every state switches to a strictly better move under those values, until
  the policy is stable. Termination is by monotonicity (each switch strictly increases the bounded values,
  so no policy repeats and the finite policy space is exhausted) — no floating-point convergence threshold.
- Grouping every enabled action into a single move recovers `reach_probability` exactly (a DTMC has no
  choice); pinned as a differential test against the gambler's-ruin walk.
- `optimize="min"` is added in the entry above (it needs the `S0min` precomputation the max case does not).
- Corpus pins a two-gamble MDP whose max value is hand-computable: move A is a fair coin (1/2), move B is
  weighted 2:1 (2/3), so the max scheduler picks B and `reach_probability_mdp` returns exactly `2/3`.

### Added — `musil.probabilistic`: exact DTMC reachability probability

- `reach_probability(model, target, weight=...)` returns the EXACT probability of eventually reaching a
  target set, treating the reachable graph as a discrete-time Markov chain: each state's enabled actions
  carry a relative `weight(name, state)` (default `1`, i.e. uniform) that normalises into a distribution
  over successors. The answer is a `fractions.Fraction` — no floating-point error, no dependency (numpy
  stays an optional accelerator only).
- The standard three-way split (Baier & Katoen, *Principles of Model Checking*, ch. 10): target states have
  probability 1; states that cannot reach the target (found via `reaches`) have probability 0; the rest
  solve the linear system `x_s = sum_s' P(s, s') x_s'` by Gauss-Jordan elimination over the rationals.
  Truncated exploration raises rather than returning an inconclusive number.
- Corpus pins the fair symmetric random walk (gambler's ruin): `reach_probability` on 0..N equals the
  theory closed form `i/N` for every start `i`, a known-verdict oracle independent of musil. This layer is
  the base for the MDP reachability that follows.

### Added — `musil.por`: partial-order reduction mechanism + soundness gate

- POR fires only an *ample set* of actions per state instead of every interleaving. This first layer ships
  the MECHANISM and the GATE (the risky automatic ample-set computation lands on top, guarded):
  - `explore_por(model, ample=...)` builds the reachable graph firing only `ample(state, enabled) -> subset`
    at each state (`ample = lambda state, enabled: enabled` is exactly `explore`).
  - `por_sound(model, ample)` validates that an ample choice is safe before it is trusted: the reduced
    reachable set must be a subset of the full one, and the SAME invariants must be violable in both — an
    ample set that drops the only path to a bug makes these disagree. Same discipline as
    `symmetry_reduction_sound` / `footprint_sound`; certifies SAFETY preservation (deadlock/liveness need
    the extra proviso, called out and left to a later step).
  - `independent(a, b, state)` is the concrete per-state independence test (both enabled, neither disables
    the other, and they commute) the ample-set computation will rest on — testable concretely because
    musil's `enabled`/`apply` are pure. Corpus pins that the trivial ample matches `explore` and is sound.

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
- `GeneralizedBuchi`: several acceptance sets (a run must visit EACH infinitely often) — the exact shape
  the GPVW construction produces (one acceptance set per `Until`), so the engine runs it directly without
  degeneralizing. `has_accepting_run` finds a reachable non-trivial SCC that intersects every acceptance
  set (empty sets accept any infinite run). Product construction is now the shared `_product` used by both
  `Buchi` and `GeneralizedBuchi`. Validated on hand-built generalized automata over the traffic light.
- `GeneralizedBuchi.from_ltl(formula)`: the GPVW tableau construction — an LTL formula (put in NNF first)
  becomes the automaton accepting exactly its satisfying model runs, one acceptance set per
  `Until`/`Eventually` subformula. This is the general LTL engine's front half. Validated by DIFFERENTIAL
  testing: for the reducible fragment, `from_ltl(Not(phi)).has_accepting_run(explore(m))` agrees with the
  trusted `check_ltl` reductions across many formula/model combinations, plus hand-verified `Until`/`Next`/
  nested cases. Not yet wired into `check_ltl` (the wiring step adds terminal-state stuttering, see
  `LTL_NOTES.md`); building and trusting the front half first.
- `check_ltl` now checks ARBITRARY LTL: the reducible shapes still fast-path to `check`/`check_liveness`
  (with traces), and everything else — `Next`, `Until`, `Release`, `WeakUntil`, arbitrary nesting, bare
  state formulas — falls through to the general engine (`GeneralizedBuchi.from_ltl(Not(phi))` +
  `has_accepting_run`). Terminal/deadlock states are stutter-extended so their finite runs get the right
  infinite-run semantics. The engine path returns a `Result` (`kind="ltl"` on violation); a counterexample
  lasso from the engine is still to come. Corpus pins general-LTL verdicts (`X`, `U`) on the traffic light.
- `GeneralizedBuchi.accepting_lasso(graph)` extracts a concrete counterexample from an accepting run: a
  stem to the accepting SCC plus a cycle visiting every acceptance set, mapped back to model states.
  `check_ltl`'s engine path now returns it as the `Result.trace` (starting `<init>`, then the stem, then
  one iteration of the repeating cycle), so a general-LTL violation carries a real witness, not just a
  verdict.

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
