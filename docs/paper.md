# musil: Unified Open-System Verification for Python

**Draft** — targeting OOPSLA tool track / ISSTA / ECOOP tool paper

---

## Abstract

We present musil, an open-source Python library for explicit-state model checking and
deterministic simulation testing (DST) of distributed systems. musil makes two contributions:

1. **Open-system verification.** The `check_open` API composes a system model with one or more
   adversarial `EnvironmentSpec` objects — contracts that carry non-deterministic behaviors,
   invariant guarantees, and named `Assumption` proof obligations. The BFS explores every
   adversarial move; unverified assumptions surface as residual obligations in the result. This
   directly operationalizes Interface Automata (de Alfaro & Henzinger 2001) and
   contract-based design (Benveniste et al. 2012) in runnable Python.

2. **Pre-built adversarial environment library.** musil ships five platform environments — K8s,
   AWS, Linux, seL4, etcd — each grounded in primary sources (formal proofs, SLA documents,
   kernel documentation). The seL4 module explicitly encodes the distinction between *verified*
   properties (capability integrity; Klein et al. SOSP 2009) and *axioms* (hardware memory
   safety; the proof's trusted computing base). This is the first tool to make this layering
   directly executable.

To our knowledge, musil is the **first Python library to unify explicit-state model checking,
deterministic simulation testing, and open-system contract verification** under a single,
dependency-free framework with fewer than 2,000 source lines.

---

## 1  Introduction

Distributed systems fail in complex ways. Two complementary approaches exist:

- **Model checking** explores all reachable states to find safety violations.
  Tools like TLA+, Alloy, and Spin are powerful but require learning a separate specification
  language and do not compose naturally with production code.

- **Deterministic simulation testing** (DST) executes real code under a seeded fault injector.
  FoundationDB, TigerBeetle, and Antithesis demonstrate that DST catches bugs that model
  checking misses (because it runs real code) and misses bugs that model checking catches
  (because the state space is bounded by the seed).

musil unifies these approaches: the same state type and invariants work in both `check(model)`
(exhaustive BFS) and `simulate(factory, seeds=...)` (seeded fault injection). A system
developer writes the model once and uses both tools.

The open problem musil addresses: neither model checking tools nor DST frameworks support
**open-system contracts** — the ability to verify a system against an adversarial external
component while keeping the assumptions about that component explicit and machine-readable.

---

## 2  Background and Related Work

### 2.1  Interface Automata

De Alfaro & Henzinger (ESEC/FSE 2001) introduced *Interface Automata* to specify the
assumptions a component makes about its environment, and the guarantees it provides in return.
Composition is defined only when the assumptions of one component are implied by the guarantees
of the other.

musil's `EnvironmentSpec` directly implements this model: `behaviors` are the environment's
output actions, `guarantees` are the environment's safety invariants (mapped to qualified
invariant names in the composed model), and `assumptions` are the obligations that must hold
for the composition to be valid.

### 2.2  Contract-Based Design

Benveniste et al. (INRIA RR-8147, 2012) generalize Interface Automata to
*assume-guarantee contracts* (A, G): a component satisfies a contract if, whenever the
environment satisfies assumption A, the component satisfies guarantee G. The theory supports
compositional verification: if sub-contracts are verified independently, the composed
contract holds.

`check_open(system, *envs)` implements this compositionally:
- Each `env` contributes its `behaviors` as additional non-deterministic actions
  (the adversarial environment can take these moves at any time)
- Each `env` contributes its `guarantees` as additional invariants that must hold in all
  reachable states
- Unverified `Assumption` objects from each env are returned as residual proof obligations

### 2.3  I/O Automata

Lynch & Tuttle (1987) partition the alphabet of an automaton into *input* actions
(controlled by the environment) and *output* actions (controlled by the system).
In musil, `env.behaviors` corresponds to input actions and `system.actions` to output actions.
`check_open` merges both and applies BFS — this is sound because the BFS is already
non-deterministic over all enabled actions.

### 2.4  seL4's Explicit Assumption Layering

Klein et al. (SOSP 2009) prove full functional correctness of the seL4 microkernel in Isabelle/HOL.
The proof is explicitly conditional on a *trusted computing base* (TCB): the hardware must execute
instructions faithfully, physical memory must not corrupt silently. These assumptions are not proved
within the system — they are *axioms* that bound the trust boundary.

musil's `Assumption` type reifies this distinction with `status ∈ {"axiom", "verified", "unverified"}`.
The seL4 environment module (`musil.environments.sel4`) encodes:

- `sel4:hardware-memory-safety` — `status="axiom"`, citing SOSP 2009 § 2
- `sel4:capability-integrity` — `status="verified"`, citing SOSP 2009 § 4 (excluded from
  residual obligations)
- `sel4:ipc-liveness` — `status="unverified"` (liveness is outside the functional correctness proof)

This is the first tool to make the TCB / verified / unverified layering directly executable and
machine-readable.

### 2.5  Related Tools

| Tool | Model checking | Simulation | Open-system contracts |
|---|---|---|---|
| TLA+ / TLC | ✓ | — | — |
| Alloy | ✓ | — | — |
| Spin | ✓ | — | — |
| Antithesis | — | ✓ | — |
| FoundationDB simulation | — | ✓ | — |
| QuickCheck/Hypothesis | — | ✓ | — |
| **musil** | **✓** | **✓** | **✓** |

None of the above tools combine all three capabilities. musil is additionally:
- Pure Python, no DSL to learn, no external solver
- Dependency-free (no third-party runtime dependencies)
- Under 2,000 source lines

---

## 3  Design

### 3.1  Closed-System API

```python
from musil import Action, Model, check

@dataclass(frozen=True)
class State:
    phase: str

model = Model(
    init=State("idle"),
    actions=[
        Action("start", lambda s: s.phase == "idle", lambda s: State("running")),
        Action("stop",  lambda s: s.phase == "running", lambda s: State("idle")),
    ],
    invariants={"known": lambda s: s.phase in {"idle", "running"}},
)
result = check(model)
assert result.ok
```

`check` performs BFS from `model.init`, applying every enabled action at each state. When an
invariant fails or a non-terminal deadlock is reached, it returns a `Result` with `ok=False`
and the shortest trace to the violation.

### 3.2  Open-System API

```python
from musil.env import check_open
from musil.env import Assumption, EnvironmentSpec

crash_env = EnvironmentSpec[State](
    name="platform",
    behaviors=[
        Action("crash", lambda s: s.phase == "running", lambda s: State("crashed")),
    ],
    assumptions={
        "no-infinite-crash": Assumption(
            name="no-infinite-crash",
            description="The platform does not crash indefinitely",
            status="unverified",
        ),
    },
)
result = check_open(model, crash_env)
```

`check_open` merges `crash_env.behaviors` into the system's actions and runs `check` on the
composed model. The BFS now explores adversarial crashes at every state where the guard holds.
Unverified assumptions are returned in `result.unverified_assumptions`.

### 3.3  Assumption Status Semantics

| Status | Meaning | Appears in `unverified_assumptions` |
|---|---|---|
| `"verified"` | Proved (formally or by tested code) | No |
| `"axiom"` | Trusted but unprovable from within the system | Yes |
| `"unverified"` | Stated but not yet proved | Yes |

`"verified"` assumptions are silently excluded because they add no residual obligation.
`"axiom"` assumptions appear because, while they may be well-founded (like seL4's hardware TCB),
they bound the trust boundary and must be communicated to the user.

### 3.4  Simulation Integration

The same `EnvironmentSpec` concepts are implemented in simulation via `AdversarialNode`:

```python
from musil.sim import simulate
from musil.environments.k8s import eviction_notifier

report = simulate(
    lambda: {"app": MyApp(), "k8s": eviction_notifier()},
    seeds=range(200),
    max_steps=1000,
    invariants={"alive": lambda nodes: nodes["app"].alive},
)
```

`AdversarialNode` uses the simulation's seeded RNG, so every `seed` produces a deterministic
fault sequence. This enables reproducing bugs found in simulation tests.

`NetworkModel(mutate=...)` adds Byzantine wire-level corruption on top of loss/duplication:

```python
def corrupt(src: str, dst: str, payload: object) -> object | None:
    if isinstance(payload, int):
        return payload ^ 0xFF  # flip low byte
    return payload

network = NetworkModel(loss_rate=0.1, mutate=corrupt)
```

---

## 4  Implementation

musil is implemented in pure Python 3.12 with no runtime dependencies. The core modules are:

| Module | Lines | Responsibility |
|---|---|---|
| `musil.core` | ~250 | BFS, `Model`, `Action`, `Result`, `check`, `explore` |
| `musil.env` | ~80 | `Assumption`, `EnvironmentSpec`, `OpenResult`, `check_open` |
| `musil.sim` | ~400 | `Simulator`, `NetworkModel`, `AdversarialNode`, `simulate` |
| `musil.environments.*` | ~600 | Pre-built K8s, AWS, Linux, seL4, etcd environments |
| `musil.liveness` | ~120 | SCC-based liveness checking (`check_liveness`) |
| `musil.refine` | ~120 | Refinement checking between abstract and concrete models |
| `musil.conformance` | ~100 | Trace-based conformance testing against recorded traces |

Total: ~1,700 source lines.

**PEP 695 generics.** musil uses Python 3.12's PEP 695 syntax (`def check[S: Hashable](...)`
and `class EnvironmentSpec[S: Hashable]`) throughout. This allows type checkers (pyright strict
mode) to verify that state types, action guards, and invariants are all consistent at the call
site — catching mismatches at development time.

**Frozen dataclasses as states.** The BFS stores visited states in a `set`. Frozen dataclasses
are hashable by structural equality, which means the BFS correctly identifies revisited states
regardless of how the state was constructed.

---

## 5  Evaluation

### 5.1  K8s scheduler with pod eviction

A minimal distributed service: job queue with bounded concurrency, running inside a K8s cluster.
The environment model injects pod evictions (scheduler removes a pod), OOM kills, and
rate-limited rescheduling. Invariant: "at most N jobs running concurrently."

```python
env = pod_eviction(
    can_evict=lambda s: s.status == "running",
    on_evict=lambda s: replace(s, status="evicted"),
)
result = check_open(model, env)
```

- Without retry logic in the service: `check_open` finds a trace where eviction leaves the
  service "evicted" with no way back — deadlock.
- With retry logic: `check_open` passes and reports three unverified assumptions (node capacity,
  scheduler liveness, PDB rate bound).

### 5.2  Multi-environment composition: K8s + AWS + etcd

A service that writes data to S3 and reads config from etcd, running on K8s.
Three simultaneous environments: pod eviction, API throttling, leader election.

```python
result = check_open(service, k8s_env, aws_env, etcd_env)
```

The BFS explores all interleavings of evictions, throttles, and leader changes. It finds a
counter-example: the service's retry budget (5 retries) can be exhausted by repeated evictions,
leaving it permanently non-running. This is a real design flaw: the retry counter is shared
across all fault types, so a burst of evictions can use up the budget before throttle errors
are retried. The trace is 12 steps.

Residual proof obligations:
- `k8s:node-capacity`, `k8s:scheduler-liveness`, `k8s:eviction-rate-bounded` (K8s docs)
- `aws:s3-eventual-delivery`, `aws:region-availability`, `aws:throttle-transient` (AWS SLA)
- `etcd:quorum-maintained`, `etcd:bounded-leader-election`, `etcd:compaction-bounded` (etcd docs)

Excluded (verified): `aws:iam-correctness`, `etcd:unique-leader`.

### 5.3  seL4 capability revocation

A system that holds a capability to an IPC endpoint. The environment model injects capability
revocations (parent revokes access). Invariant: "the system never uses a revoked capability."

```python
env = capability_revocation(
    can_revoke=lambda s: s.cap_valid,
    on_revoke=lambda s: replace(s, cap_valid=False),
)
result = check_open(model, env)
```

Residual obligations include `sel4:hardware-memory-safety` (axiom — the TCB) and
`sel4:ipc-liveness` (unverified). `sel4:capability-integrity` is *excluded* because the seL4
formal proof provides it; the user's proof obligation is only the hardware assumption that
seL4's verification cannot discharge from within.

This makes the trust boundary explicit and inspectable, without requiring the developer to
read the seL4 paper to understand what is and isn't guaranteed.

### 5.4  TCAS II Resolution Advisory coordination

TCAS II (Traffic Collision Avoidance System) is a safety-critical aviation protocol that has
attracted extensive formal verification work: RSML specification analysis (Heimdahl & Leveson
1994–1996), SMV model checking (Chan et al. 1998), hybrid I/O automata proofs (Lygeros &
Lynch 1997; Livadas, Lygeros & Lynch 2000), PVS theorem proving of the RA detection algorithm
(Muñoz et al. 2013), and KeYmaera differential-dynamic-logic proofs for the successor system
ACAS X (Jeannin, Platzer et al. 2015, 2017). This body of work makes TCAS II an unusually
well-documented case study for comparing verification approaches.

The `examples/tcas.py` model encodes the TCAS II v7.1 coordination protocol accurately:
own aircraft selects an RA sense (CLIMB or DESCEND) and broadcasts a Vertical Resolution
Advisory Complement (VRC) constraint to the intruder via a UF=16 addressed Mode S message
(BDS register 0x30). The VRC constraint forces the intruder to pick the complementary sense.
This asymmetric, constraint-based protocol (rather than symmetric "negotiation") is reflected
directly in the state: an `Aircraft` carries `vrc_received` alongside its own `ra`.

Four scenarios are checked:

1. **Closed model** — both pilots follow their RAs. `check` verifies the invariant
   "both aircraft never maneuver in the same vertical direction" holds for all traces.

2. **Überlingen (open model)** — the environment injects `pilot:deviates-from-ra`, modeling
   a pilot who follows an ATC instruction over the active TCAS RA (the 2002 Überlingen disaster;
   71 killed). `check_open` finds the counterexample in 5 steps and surfaces
   `PILOT_FOLLOWS_RA` (status: unverified; source: BFU AX001-1-2/02, 2004) as a residual
   proof obligation.

3. **ATC suppression enforcement (open model)** — the environment's deviation action is guarded
   by `_atc_suppressed`, modeling a "TCAS-only" avionics policy. `check_open` passes;
   `ATC_SUPPRESSED_DURING_RA` surfaces as the residual assumption (source: ICAO Annex 2,
   Amendment 42).

4. **v7.1 reversal + Tenerife (open model)** — `reversal_model` adds an `own:ra=reversed`
   system action (the DO-185B v7.1 mechanism: own reverses sense when intruder has an RA but
   hasn't maneuvered within the timing window). The environment injects
   `intruder:maneuvers-with-old-ra`, modeling the intruder executing its original RA while
   re-coordination is incomplete (2011 Tenerife near-collision; Thomas Cook / Finnair).
   `check_open` finds the counterexample in 7 steps and surfaces `INTRUDER_FOLLOWS_REVERSAL`
   (source: CIAIAC A-032/2011; Eurocontrol SISG 2017 reports ~25% RA non-compliance).

The TCAS example demonstrates a key feature: the same `Assumption` mechanism used for platform
contracts (K8s eviction rate, seL4 TCB) applies equally to human-behavioral assumptions
(pilot RA compliance) and to protocol timing assumptions (intruder responds within window).
Every unverified assumption names its primary incident report as a `source` — the model is
self-documenting about what it relies on and where those assumptions have historically failed.

The connection to Livadas, Lygeros & Lynch (2000) is direct: their Hybrid I/O Automata model
partitions TCAS behaviors into *input actions* (the environment can inject) and *output actions*
(the system produces). musil's `EnvironmentSpec.behaviors` = input actions; `Model.actions` =
output actions. musil is the first tool to make this partition runnable in Python with
machine-readable, citable assumptions attached to each input action.

### 5.5  Control-plane verification driven by production code

The preceding case studies model a system *for* verification. This one inverts that: it points musil
at the **already-written code of an industrial control plane** and checks the *real* artifacts,
demonstrating the "zero-drift" claim end to end. The control plane already had a hand-built
correctness model — a guarded labeled transition system per resource, a set of cross-resource
invariants, and a reconcile loop — but verified them only by *sampling* (property-based fault
injection), never exhaustively.

musil closes that gap with no separate specification. The model's actions are generated directly from
the production transition table (`multi_status_field_actions`); the safety property is the production
`check(world) -> [Violation]` function itself, adapted with `invariant_from_violations` so the
counterexample names which sub-rule and entity broke. Because the model *is* the code's data, it
cannot drift from it. Four results illustrate the workflow:

1. **A real incident, reproduced.** A prior outage — a wedged node left resources stuck off `running`,
   and because a serving capability was coupled to a resource being `running`, an active dependency
   dropped from a routing table — is reproduced as a one-step counterexample from the real transition
   table, and the structural fix (serving depends only on the dependency's own validity, never a
   liveness signal) is then *verified* to close it over the whole reachable space.

2. **A specification/code drift.** Driving the *implemented* invariant (not a re-typed copy) exposed
   that it is weaker than its documentation: the doc requires a placed resource's node be `online`,
   the code only forbids a `removed` node. Exhaustive checking surfaced a state the code accepts but
   the spec rejects — a discrepancy invisible to tests written against either alone.

3. **Find rough edges, then verify the fix.** For each rough edge, the *corrected* design (e.g. node
   removal atomically reschedules a placed resource; stateful resources trigger recovery rather than a
   blind reap) is re-checked and shown to hold over every reachable state — `reachable_violations`
   enumerates the exact set of invalid cross-resource states a guard must exclude, turning "find a
   bug" into "derive the guard specification."

4. **Liveness as a response property.** The untimed form of "no resource stuck in a transient state"
   is the leads-to property `placed ~> running`, which `check_liveness(..., leadsto_from=...)` shows
   holds only under *strong* fairness of the reconciler's stabilizing step — a concrete design
   obligation, not a vague "the reconciler should make progress."

Methodologically, this case study is also where most of musil's closed-system API was *driven into
existence*: each capability above (`invariant_from_violations`, `multi_status_field_actions`,
`reachable_violations`, `leadsto_from`, ordered channels) was added because faithfully modeling the
real system demanded it — the place where the tool forced a distortion named the missing feature.
The verification models run as a regression suite, so a future edit to the production state machine
that silently reopens one of these rough edges fails CI.

---

## 6  Limitations

- **State explosion.** BFS is exponential in the number of concurrent components. The
  `max_states` parameter caps exploration, trading completeness for tractability.
  In practice, the models we've seen stay under 100k states.

- **Single-threaded exploration.** The BFS runs in one process; there is no built-in parallel or
  sharded `check`. Actions are Python closures, which `multiprocessing` cannot pickle to worker
  processes, and the GIL serializes a CPU-bound thread pool — so exploration does not scale across cores
  today. To fit a large space in a CI budget, *reduce* it rather than parallelize it: `Model.footprint`
  to memoize an expensive `actions_fn`, symmetry reduction (`canonical_by_sorting` /
  `canonical_by_permutations` / `canonical_by_fields`, each gated by `symmetry_reduction_sound`) to
  collapse interchangeable identities, and a tighter `max_states` or a smaller initial scope. Where the
  state space partitions naturally, run the independent per-partition models as separate checks (e.g. one
  per shard under a forked test runner). Use `profile` to find where the time actually goes before
  reaching for any of these.

- **Liveness only via SCC.** `check_liveness` finds strongly-connected components with no
  outgoing transitions. This catches liveness violations where the system loops forever, but
  not linear-time temporal properties (LTL formulae).

- **Simulation is not exhaustive.** `simulate` explores a fixed set of seeds — it cannot
  guarantee that no fault sequence causes a violation. It is best used as a complement to
  model checking (model checking for design, simulation for implementation).

- **Assumption verification is external.** musil surfaces unverified assumptions but does not
  prove them. The user must bring their own evidence (formal proofs, load tests, SLA documents).

---

## 7  Conclusion

musil demonstrates that unified open-system verification — model checking, simulation testing,
and contract verification with explicit assumptions — is achievable in a small, dependency-free
Python library. The pre-built environment library shows that real platform assumptions
(K8s eviction rates, seL4 formal proofs, Raft safety) can be expressed as first-class,
machine-readable contracts that travel with the verification result.

We believe musil fills a gap in the Python ecosystem: no existing tool combines all three
capabilities in a form that is easy to adopt incrementally alongside production code.

---

## References

- De Alfaro, L., & Henzinger, T. A. (2001). *Interface Automata.* ESEC/FSE.
- Benveniste, A., Caillaud, B., Nickovic, D., Passerone, R., Raclet, J.-B., Reinkemeier, P.,
  Sangiovanni-Vincentelli, A., Damm, W., Henzinger, T. A., & Larsen, K. G. (2012).
  *Contracts for system design.* INRIA Research Report RR-8147.
- Lynch, N. A., & Tuttle, M. R. (1987). *Hierarchical correctness proofs for distributed
  algorithms.* PODC.
- Klein, G., Elphinstone, K., Heiser, G., Andronick, J., Cock, D., Derrin, P., Elkaduwe, D.,
  Engelhardt, K., Kolanski, R., Norrish, M., Sewell, T., Tuch, H., & Winwood, S. (2009).
  *seL4: Formal Verification of an OS Kernel.* SOSP.
- Ongaro, D., & Ousterhout, J. (2014). *In Search of an Understandable Consensus Algorithm.*
  USENIX ATC.
- Castro, M., & Liskov, B. (1999). *Practical Byzantine Fault Tolerance.* OSDI.
- Lamport, L., Shostak, R., & Pease, M. (1982). *The Byzantine Generals Problem.* TOPLAS.
- Newcombe, C., Rath, T., Zhang, F., Munteanu, B., Brooker, M., & Deardeuff, M. (2015).
  *How Amazon Web Services Uses Formal Methods.* CACM.
- Lygeros, J., & Lynch, N. (1997). *On the Formal Verification of the TCAS Conflict Resolution
  Algorithms.* 36th IEEE Conference on Decision and Control.
- Livadas, C., Lygeros, J., & Lynch, N. A. (2000). *High-Level Modeling and Analysis of the
  Traffic Alert and Collision Avoidance System (TCAS).* Proceedings of the IEEE, 88(7).
- Chan, W., Anderson, R. J., Beame, P., Burns, S., Modugno, F., Notkin, D., & Reese, J. D.
  (1998). *Model Checking Large Software Specifications.* IEEE Transactions on Software
  Engineering, 24(7).
- Muñoz, C., Narkawicz, A., & Chamberlain, J. (2013). *A TCAS-II Resolution Advisory Detection
  Algorithm.* AIAA GNC Conference. NASA/TM-2014-218082.
- Jeannin, J.-B., Ghorbal, K., Kouskoulas, Y., Gardner, R., Schmidt, A., Zawadzki, E., &
  Platzer, A. (2015). *A Formally Verified Hybrid System for the Next-Generation Airborne
  Collision Avoidance System.* TACAS. LNCS 9035.
- Jeannin, J.-B., Ghorbal, K., Kouskoulas, Y., Schmidt, A., Gardner, R., Mitsch, S., &
  Platzer, A. (2017). *A Formally Verified Hybrid System for Safe Advisories in the
  Next-Generation Airborne Collision Avoidance System.* International Journal on Software Tools
  for Technology Transfer, 19(6).
