# Changelog

All notable changes to musil are documented here. Versioning is [SemVer](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [0.11.0] - 2026-08-12

Four of the five additions from
[issue #1](https://gitlab.com/jorgeecardona/musil/-/work_items/1), raised by adopting musil in a
classifier workspace. All four are stdlib-only, so `pip install musil` still installs zero
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
- Prompted by feedback from adopting musil in a classifier workspace
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
