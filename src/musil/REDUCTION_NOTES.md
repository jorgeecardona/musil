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

## References

Flanagan & Godefroid, "Dynamic Partial-Order Reduction for Model Checking Software" (POPL 2005);
Clarke, Grumberg, Peled, *Model Checking* (ch. on partial-order reduction). See
`docs/specs/RESEARCH.md`.
