# Memory-bounded search (bitstate / hash-compaction) — REJECTED; musil is exact-only by design

`check`/`explore` hold the full `seen` set of reachable states in RAM, so the reachable space must fit in
memory. Rich states (large frozen dataclasses) hit that wall before the time budget. This is GitLab #2 item
4 (SPIN's supertrace/bitstate; PRISM/TLC have related modes). It is designed here but **will not be
shipped**: see the decision at the end. The reason is that it changes something the rest of musil does not —
it makes a clean run APPROXIMATE, evidence with a quantified miss-probability rather than a proof.

## The two classic techniques

**A. Hash-compaction** (Wolper & Leroy 1993; Stern & Dill 1995). Store a wide hash `h(s)` (say `k` bits)
in a `set[int]` / `set[bytes]` instead of the full state. Memory is `~k/8` bytes per state (e.g. 8 bytes
for 64-bit, 16 for 128-bit) instead of the whole dataclass. A state counts as "seen" iff its hash is
already present. A MISS happens only when two *distinct* reachable states share a hash. For `n` reachable
states and a `k`-bit hash the birthday bound gives `P(miss) ≈ n² / 2^(k+1)`:

| k (bits) | n = 10^6            | n = 10^7            |
|----------|---------------------|---------------------|
| 64       | ~2.7e-8             | ~2.7e-6             |
| 128      | ~1.5e-27            | ~1.5e-25            |

So with a 128-bit hash the miss probability is negligible for any `n` musil targets, and it is *quantified*
— the result can report the exact bound.

**B. Bitstate / supertrace** (Holzmann). A fixed bit-array of `2^m` bits; each state sets `d` bits chosen
by `d` independent hashes (a Bloom filter). Memory is FIXED at `2^m` bits regardless of `n`. Coverage (the
"hash factor") is `2^m / n`; the miss probability climbs as `n` approaches `2^m`. Reports coverage rather
than a birthday bound.

Both are approximate. The difference: hash-compaction's memory is `O(n)` (small per state) with a miss
probability you drive to negligible by widening the hash; bitstate's memory is `O(1)` (a fixed array) but
its miss probability is only controlled by how much of the array you fill.

## Why this is not just an implementation

Everything else in musil is EXACT: a green `check` means the whole reachable space was swept. Every
reduction that could drop states (symmetry, POR, footprint memoization) ships behind a soundness gate that
proves it did not (`symmetry_reduction_sound`, `por_sound`, `footprint_sound`). Bitstate/hash-compaction
cannot have such a gate — the miss is probabilistic, so no run can certify "no state was dropped"; only the
*probability* bound can be asserted. A clean bitstate run is therefore evidence, not proof. Introducing that
into a tool whose whole value proposition is soundness is a philosophy call, not a coding one, and must be:

- **Named and typed as approximate.** A separate `check_compact` (not a silent `check` flag), returning a
  result that carries `approximate=True` and the computed `miss_probability` bound. `assert_ok`-style
  helpers and `__str__` must never present it as "proven".
- **Never the default**, and never conflated with an exact verdict in caches, diffs, or reports.

## The counterexample-trace problem

With only hashes in `seen`, the path to a violation cannot be rebuilt from the `seen` structure — hashes do
not map back to states. Options, in increasing effort:

1. **Report the violating state only** (it is in hand at detection) plus states-visited and the
   miss-probability, with an empty `trace`, documented as "reproduce in exact mode on a reduced instance to
   get the full trace." This is SPIN's real two-phase workflow (find big in bitstate, reproduce small in
   exact) and is the honest MINIMAL first cut.
2. **Store parent pointers** as `hash -> (parent_hash, action_name)` and RE-RUN from the initial state
   following the recorded action-name sequence to rebuild the concrete states for the trace (SPIN does a
   variant of this). Costs a second pass and assumes the action names replay deterministically.
3. **Keep full parent states for the current BFS frontier only** — bounded memory, but reconstructs traces
   only up to frontier depth, so it fails exactly on the deep violations bitstate exists to find. Not worth
   it.

Recommended: option 1 for the first cut; option 2 only if users need in-mode traces.

## Recommendation

If musil adopts an approximate mode at all, ship **variant A (hash-compaction) as a separate
`check_compact(model, *, hash_bits=128, max_states=...)`**, not a flag on the shared `check` kernel (isolate
the risk; promote to a flag later only if wanted). Rationale: `O(n)` small-digest memory, a *quantified*
negligible miss-probability the result reports, and a much simpler story than bitstate's coverage
accounting. Bitstate (variant B) only matters when even `O(n)` digests do not fit, which is past musil's
current target sizes.

Gate: a DIFFERENTIAL test that on every corpus model small enough to fit exactly, `check_compact` returns
the SAME verdict as `check` (they must agree in the collision-free regime). That test exercises the sweep
and the reporting; it cannot test the miss behaviour (probabilistic), only that the reported bound is
computed correctly.

## Decision (2026-08-30): rejected — musil is exact-only by design

The user's ruling: **no implementation may allow a miss. A nonzero miss probability is not an option.** So
both techniques above are out — a clean `check` is a PROOF that the whole reachable space was swept, never
evidence-with-a-probability. This is musil's identity as a soundness-first checker, consistent with every
reduction it already ships (symmetry, POR, footprint memoization) being gated by a check that proves no
state was dropped; a probabilistic miss can have no such gate, so it cannot exist here. Users who genuinely
need bitstate-scale approximate search use SPIN.

#2.4 is therefore **permanently deferred** (closed as won't-do), not parked pending effort.

### If memory ever becomes the binding constraint, the sound (zero-miss) options are

These keep `check` a proof and are the only directions musil would consider — none trades away exactness:

- **Lossless state compression.** Store a smaller EXACT encoding in `seen` (a canonical serialization, field
  interning / a shared dictionary of repeated substructures, delta-encoding against a parent) instead of the
  full Python object. Equality is preserved exactly, so there is zero miss — it is the same search using
  fewer bytes per state. This is the first thing to reach for.
- **Collision detection done right.** Hashing is fine for BUCKETING as long as a hash hit is confirmed by a
  full-state comparison (which is exactly what Python's own `set`/`dict` already do). The unsound step is
  *dropping* the full state so the comparison cannot happen; keep the state (possibly compressed, above) and
  there is no miss.
- **External / on-disk `seen` set.** Spill the visited set to disk (sorted runs, or an embedded key-value
  store keyed by the exact state encoding). Zero miss, RAM no longer the ceiling, at the cost of speed. A
  pure-stdlib option (`sqlite3`, `shelve`) keeps the dependency policy.

None of these is urgent for the bounded models musil targets; they are recorded so the exact-only stance has
a concrete forward path that never reintroduces a miss.

Everything else in GitLab #2 is shipped: item 1 (coverage & vacuity) via `musil.metrics`
(`coverage`, `invariant_coverage`, `state_space_metrics`, `solution_cardinality`); item 2 (LTL layer) via
`musil.ltl` (`check_ltl` + the general Büchi engine, patterns re-expressed as sugar); item 3 (probabilistic
DTMC/MDP) via `musil.probabilistic` (`reach_probability`, `reach_probability_mdp` max/min, step-bounded,
`expected_reward`, `expected_reward_mdp`). Item 4 is this note.

## References

- Holzmann, "An Analysis of Bitstate Hashing" (1998) — supertrace/bitstate, coverage/hash factor.
- Wolper & Leroy, "Reliable Hashing without Collision Detection" (CAV 1993); Stern & Dill, "Improved
  Probabilistic Verification by Hash Compaction" (1995) — hash-compaction and its birthday bound.
