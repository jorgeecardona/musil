# Changelog

All notable changes to musil are documented here. Versioning is [SemVer](https://semver.org/).

## [Unreleased]

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
