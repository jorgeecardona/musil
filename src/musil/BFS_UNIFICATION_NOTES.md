# BFS-loop unification (roadmap 1b) — shared primitives, not one driver loop

Roadmap item (1b) is "unify the four BFS loops (check / check_all / explore / profile) behind one shared core
primitive." This note records what that means in practice, what is done, and why a single driver loop is the
wrong target for two of the four.

## The four loops and what actually differs

All four are the same breadth-first sweep of the reachable graph (seed the frontier from the initial states,
canonicalize and dedup, pop FIFO, expand enabled successors, honour `max_states`). They differ ONLY in the
per-state work and the control flow around it:

- **check** — checks invariants BEFORE expanding, and EARLY-EXITS on the first violation/deadlock without
  expanding that state. Tracks a parent map for the shortest-trace counterexample.
- **check_all** — same, but COLLECTS the shortest witness for each distinct violation instead of exiting;
  sweeps the whole space.
- **explore** — no invariants, no early-exit. Records the FULL labelled edge list per state (`dict[S, edges]`)
  and returns a `Graph`. Keyed by state (hashable required); no `key`/identity indirection.
- **profile** — the instrumented mirror of check's sweep: it TIMES each primitive (canon, identity, enabled,
  apply, invariant) separately, so it must inline them with a `perf_counter()` around each.

## What is shared (the actual "one primitive")

The soundness-critical primitive is the successor computation, extracted so it cannot drift between paths
(the 089aed0 bug: a successor was canonicalized in one loop but not the other):

- `_successors` — the ONE place a successor is `canon(action.apply(state))`. Used by check, check_all, and
  explore.
- `_seed_frontier` — the shared seeding (canon, identity dedup, `parent=None` roots) for check/check_all.
- `_expand` — the shared frontier expansion + `max_states` truncation for check/check_all, LAZY so the state
  that trips the cap does not apply its remaining actions.
- `_extend_frontier` — the same expansion contract from an ALREADY-COMPUTED successor list. On the
  edge-invariant path check/check_all need the successors anyway (to check each transition), so they compute
  them once and feed that list to `_extend_frontier` instead of running `_successors` a second time. (Before
  this, the edge-invariant path computed every successor TWICE per state.) Truncation matches `_expand`
  exactly: same order, same identity dedup, same cap.

check and check_all are thus fully unified: same seed, same successor computation, same expansion, differing
only in "exit on first vs collect all." explore shares `_successors`.

## Why NOT one driver loop for all four

A single generator/driver that yields each state with its successors, that all four delegate to, was
considered and rejected:

1. **check's check-before-expand-with-early-exit resists it.** check evaluates invariants BEFORE expanding a
   state and, on a violation, returns WITHOUT expanding it. A "yield each state with its successors" driver
   must expand to produce the successors, so it would either (a) expand states that check would have
   early-exited on (extra applies, and a violated state near the cap could trip `max_states` where check
   would have returned the violation first — a different `states_explored` and a different truncated flag), or
   (b) become a `send`-based coroutine so the caller can check invariants between "here is the state" and
   "now expand it." (b) is over-engineering a hot loop for no measured benefit.
2. **explore records edges, not parent chains.** Its per-state output is the full labelled edge list
   (including edges back to already-seen states), kept in a `dict[S, edges]`. check/check_all keep only the
   parent edge to each newly-seen state. Forcing both through one bookkeeping structure taxes whichever path
   does not need the other's data, and changes explore's truncated-graph edge semantics (partial vs full edge
   list on the state that trips the cap) unless replicated with surgical care.
3. **profile's whole purpose is to NOT abstract the steps.** It measures the per-primitive cost of the sweep;
   routing it through a shared driver that hides canon/identity/enabled/apply behind one call would delete the
   measurement. profile stays a separate inlined loop by design, and the corpus pins that it explores the same
   reachable set as explore/check so it cannot silently drift
   (`test_profile_explores_the_same_reachable_set`).

## Conclusion

(1b) is satisfied at the primitive level: the sweep's soundness-critical pieces (`_successors`,
`_seed_frontier`, `_expand`, `_extend_frontier`) are shared and corpus-guarded, and the four loops compose
them with their genuinely-different control flow. A further collapse into one driver loop would regress
check's laziness or profile's instrumentation, so it is deliberately NOT done. If a future change adds a fifth
sweep, it should reuse these primitives rather than hand-roll a new frontier loop.
