# Partial-order reduction — designed, deliberately deferred

musil explores **every interleaving** of concurrent actions. That is what makes it find races, and
also what makes it blow up: N independent actions generate N! orderings, most redundant. The standard
cure is **partial-order reduction (POR)** — at each state, explore only a sufficient *ample set* of
actions instead of all of them. This note records the design and, more importantly, **why it is not
shipped yet**: in a verification tool an unsound reduction silently drops reachable states and so
*misses bugs* — strictly worse than being slow. POR is correct only under conditions that are easy to
get subtly wrong, so it ships only with a soundness check (below), not before.

## Independence

Two actions `a`, `b` are **independent at state s** if they commute and neither disables the other:

- both enabled at `s`, and each still enabled after the other fires, and
- `apply(b, apply(a, s)) == apply(a, apply(b, s))` (same resulting state either order).

musil can test this *concretely* per state (it has `enabled`/`apply` as pure functions), which is a
nice advantage over tools that need a static independence relation — but it costs the very successor
computations we're trying to avoid, so it must be cached/approximated to pay off.

## Ample sets (the conditions that must ALL hold)

For each state `s`, `ample(s) ⊆ enabled(s)` must satisfy (Clarke/Peled/Godefroid):

- **C0** — `ample(s)` is empty only if `enabled(s)` is empty.
- **C1 (the key one)** — along every run from `s` in the *full* graph, no action *dependent* on an
  action in `ample(s)` can occur before some action in `ample(s)` does. (Nothing outside the ample
  set "interferes" with it first.)
- **C2 (invisibility)** — if `ample(s) != enabled(s)`, every action in `ample(s)` is *invisible* to
  the properties being checked (it doesn't change any variable an invariant reads). Otherwise the
  reduction can hide a property violation.
- **C3 (the cycle / "ignoring" condition)** — an action enabled in a cycle may not be deferred
  forever by always choosing an ample set that excludes it. Without C3 a reduction can *ignore* an
  action on a cycle and miss the states it would reach. This is the condition most often gotten wrong.

C2 interacts with musil's API: invariants are arbitrary Python predicates, so "invisible" must be
declared by the user (which variables a property reads), or conservatively approximated (treat every
action as visible -> no reduction). C3 needs cycle detection during the on-the-fly search (a stack
condition: the ample set must include an action that leaves the current DFS stack).

## How it would plug in

`explore`/`check` would take `reduce=True`. The BFS becomes a DFS (C3's stack condition needs the
search stack). At each state, compute a candidate ample set (start from one action's
*persistent set* via the concrete independence test; fall back to `enabled(s)` if C1/C2/C3 can't be
shown). The counterexample machinery is unchanged — POR preserves reachable *states* (and, with C2,
property violations), just not every path.

## Soundness gate (ships only when this passes)

POR is added only behind `reduce=True` AND with a **differential test** that is the actual proof
obligation, checked empirically on every concurrency model in the suite:

- `explore(model, reduce=True).states == explore(model, reduce=False).states` — the reduced search
  reaches exactly the same set of reachable states (for the safety fragment), and
- `check(model, reduce=True)` reports the **same** verdict (ok / same invariant / same kind) as
  `check(model, reduce=False)` on `lost_update`, `mutex` (Peterson's), the cert-vs-service race, and
  the deploy/ingress models.

If those ever diverge, the reduction is unsound and must not ship. Until POR is implemented *and* the
differential test is green, `reduce` defaults to off and the full interleaving search is the only
supported mode. For the bounded models musil targets today (tens to low thousands of states) the full
search is fast enough; POR matters when models grow, and that is when this gets built — carefully.

## Update (2026 research): the sound path forward

A literature review (primary sources below) sharpened both the design and the deferral. Three
findings change the plan:

**1. Use source sets, not the classic C0–C3 ample-set conditions.** Abdulla/Aronis/Jonsson/Sagonas
proved that being a *source set* is the **necessary and sufficient** condition for a DPOR algorithm
to be sound (explore ≥1 interleaving per Mazurkiewicz/happens-before class). Source sets subsume
ample/persistent/stubborn sets and are provably minimal — a smaller persistent set than the source
set only ever triggers sleep-set-blocked (wasted) explorations. So the C1/C2-style branch-point
obligation above is better stated as the single condition "the explored set at each scheduling point
is a source set." Provably *optimal*-DPOR (source sets + wakeup trees) is the ceiling — exactly one
interleaving per class, zero blocked explorations — but wakeup trees can cost exponential memory, so
plain **source-set DPOR is the pragmatic target**.

**2. The deferral was right: every DPOR soundness proof assumes ACYCLIC, finite, bounded-length
state spaces.** musil is stateful and *cyclic* (control loops), so basic DPOR does not transfer.
Naively stopping a run at a state-match leaves backtracking points unset and **silently drops
bug-reaching runs** (Trimananda/Yi/Demsky, VMCAI 2022 — they show a missed assertion failure; they
note Yi et al.'s earlier "cyclic" DPOR "overlooks the need for a proviso ... and can produce
incorrect results"). Shipping DPOR over musil's models therefore *requires* a **full-cycle proviso**:
stop a run only if its state matches a state from a *previous* execution, **or** matches a state from
the *current* execution **and** every enabled action in that cycle has been explored at least once.
This is the concrete replacement for the old C3 "ignoring" condition. Pair it with an explicit
acyclic/depth-bound guard.

**3. Never couple POR to the liveness engine.** Peled's standard on-the-fly POR (in SPIN for ~20
years) was *proven unsound* in CAV 2019 (Siegel, "What's Wrong with On-the-Fly Partial Order
Reduction") — "the algorithm is incorrect ... realized in Spin, which can produce an incorrect
result." The bug is precisely the C3/ignoring proviso applied to the system × Büchi product, and the
repair (Neele/Valmari/Willemse) restores soundness only for a *subclass* of property automata. So:
**POR applies to the safety/reachability fragment only** (`check` on the cert-vs-service race,
backup/restore safety, deploy/rolling-upgrade machines). `check_liveness` (ingress convergence,
scheduler liveness) stays on the existing fairness/lasso engine, uncoupled from any reduction.

**On C2 invisibility for arbitrary-predicate invariants.** Flanagan & Godefroid's insight is that
DPOR is *stateless* and computes dependencies **dynamically** from observed interactions (which state
fields an `apply` actually touched), sidestepping conservative static analysis — a good fit for
musil's pure `enabled`/`apply`. Dynamic dependency resolves *action–action* conflicts, but
*predicate-invisibility* (does this action change a field some invariant reads?) is still opaque when
invariants are arbitrary Python. Open question: extract read-sets by instrumenting field access on the
frozen-dataclass state, vs. requiring a per-invariant `reads=` annotation, vs. conservatively
treating every action as visible (no reduction). The differential soundness gate above remains the
real proof obligation regardless.

Net revised plan: `reduce=True` = **source-set DPOR + full-cycle proviso + acyclic/depth guard, for
safety runs only**; keep the differential test; keep liveness on the fairness engine.

## Status (shipped vs deferred)

- **Shipped** (`musil.por`): the MECHANISM (`explore_por` fires a caller-supplied ample set per state) and
  the GATE (`por_sound` validates that an ample choice preserves the violable-invariant set against the
  full exploration — the same discipline as `symmetry_reduction_sound`), plus `independent`, the concrete
  per-state independence test. A caller can supply an ample and validate it today.
- **Deferred**: the AUTOMATIC ample-set (persistent/source-set) computation. musil's actions are opaque
  Python callables, so there is no static dependency relation and no enabling relation to compute a
  persistent set from, and C1 needs full-graph lookahead. A sound automatic computation therefore needs
  either a caller-DECLARED static independence + enabling relation, or dynamic (DPOR) machinery whose
  soundness over cyclic state spaces needs the full-cycle proviso. Until one is built and gated, POR is
  "supply an ample, validate with `por_sound`". `independent` gives the concrete relation to build on.

## Measured: the SSP-master workload (#37)

The one non-synthetic POR benchmark (IDEAS.md #5) is a co-simulation master over N FMUs — pymodelica's
`src/modelica/ssp/master.py`, driven by `verify.master()` as a `Model[Progress]`. #37 asked for the
scaling curve *before* any POR work: n = 2..5 rollback-capable components, state count and `check` wall
time, with and without `canonicalize=`, and — because many SSP components are interchangeable — to try
symmetry **first**. Measured 2026-10-17 (musil 0.36.2, against the real pymodelica master):

| n | states | `check` | states + sym | `check` + sym | reduction | sound? |
|---|--------|---------|--------------|---------------|-----------|--------|
| 2 |     31 | 0.003s  |           23 | 0.002s        | 1.3×      | yes    |
| 3 |     63 | 0.009s  |           31 | 0.005s        | 2.0×      | yes    |
| 4 |    127 | 0.028s  |           39 | 0.010s        | 3.3×      | yes    |
| 5 |    255 | 0.078s  |           47 | 0.017s        | 5.4×      | yes    |

Plain is exactly `2^(n+3) − 1` (exponential — the independent per-component interleavings); with
symmetry it is `8n + 7` (**linear**). The reduction is `canonical_by_sorting` over the interchangeable
per-component `(time, saved)` slots, and it passes `symmetry_reduction_sound` at every n (it visits
exactly the canonical quotient, with the same invariants violable — not a lossy merge).

**Conclusion: symmetry carries this workload, so POR is not needed for it — and that deferral is now
measured, not argued from arithmetic.** An exponential space becomes linear with a sound,
already-shipped lever, extending the usable range far past where the full interleaving would stop (plain
reaches musil's 1M-state ceiling near n ≈ 17; the reduced search does not). The worked recipe —
`canonical_by_sorting` for interchangeable components in a composed model, gated by
`symmetry_reduction_sound` — ships as `examples/cosim_master_scaling.py` (the lever the pymodelica POR
issue noted was undocumented). POR stays deferred per the status above; if a workload ever appears whose
symmetry does *not* collapse it, this is the measured starting point for building it.

## Measured: parallel exploration (#17) — cores, not a reduction

`parallel_check` (`check(workers=N)`, `musil.parallel`) is NOT a reduction: it does not shrink the
reachable space, it spends more cores on whatever space is left. So it composes with symmetry rather than
competing — reduce the space first (symmetry changes the complexity class), then throw cores at the
expansion that remains. It is level-synchronous BFS fanned across `fork` processes, returning the SAME
`Result` as serial `check` (verified by equality tests across ok / invariant / deadlock / edge-invariant /
symmetry / non-hashable-key models).

The gate (#17 ships it only if it beats serial): it depends ENTIRELY on whether the model's own
`apply`/`enabled`/invariant closures cost more than pickling a state across the per-level barrier. Measured
on a grid model (16-core box, Python 3.12), serial vs `workers=`:

| workload | states | serial | w=4 | w=8 |
| --- | --- | --- | --- | --- |
| cheap transition (`work=0`) | 46 656 | 0.62s | 1.49s (**0.41×**) | 1.69s (**0.36×**) |
| cheap transition (`work=0`) | 78 125 | 1.41s | 4.79s (**0.29×**) | 2.97s (**0.47×**) |
| heavy transition (`work=400`) | 46 656 | 7.85s | 4.90s (**1.60×**) | 3.40s (**2.31×**) |
| heavy transition (`work=400`) | 78 125 | 15.58s | 8.29s (**1.88×**) | 6.43s (**2.42×**) |

Conclusion: **parallelism LOSES on cheap expansion** (2–3× slower — the state pickling across processes
dwarfs a trivial transition) and **WINS on expensive expansion** (up to ~2.4×), which is exactly the case
#17 was filed for (a 5–20s CPU-bound check with real closures). Speedup plateaus near 2.4× well below the
core count: the level-synchronous barrier and the parent's serial visited-set merge are the Amdahl ceiling,
and the per-level pickle round-trip is pure overhead serial never pays. So `workers=N` is a lever for
models whose transition relation is genuinely expensive, not a free default — hence opt-in, left at 1.

## References

- Flanagan & Godefroid, "Dynamic Partial-Order Reduction for Model Checking Software" (POPL 2005) —
  stateless DPOR, dynamic dependencies; soundness scoped to acyclic state spaces.
- Abdulla, Aronis, Jonsson, Sagonas, "Optimal Dynamic Partial Order Reduction" (POPL 2014) and the
  JACM 2017 journal version — **source sets** (necessary & sufficient), wakeup trees, optimal-DPOR.
- Trimananda, Yi/Luo, Demsky, Xu, "Stateful DPOR for ... Applications that Do Not Terminate"
  (VMCAI 2022) — the **full-cycle proviso** for sound DPOR over cyclic/stateful state spaces.
- Siegel, "What's Wrong with On-the-Fly Partial Order Reduction" (CAV 2019); Neele, Valmari,
  Willemse (LMCS) — the POR-vs-liveness/Büchi unsoundness and partial repair.
- Clarke, Grumberg, Peled, *Model Checking* (ch. on partial-order reduction) — the standard textbook
  map of the wider literature.
