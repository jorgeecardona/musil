# Inductive invariants / k-induction — what musil does, and where it stops

`check` is exhaustive **up to a scope** (`max_states`, a small `init`); a passing run proves the
invariant only within that scope. An **inductive** proof discharges it without reference to reachability:

- **base**: no reachable state violates `I` within the first `k-1` steps, and
- **step** (k-induction): along every path `s0 -> ... -> sk` whose first `k` states satisfy `I`, the
  `(k+1)`-th satisfies `I` too.

If both hold, `I` holds for every reachable state at any scope. A failing step yields a
**counterexample-to-induction**: a state satisfying `I` with a successor that breaks it, so the author
strengthens `I` rather than widening the scope.

## What ships: `check_inductive` over a finite domain

`musil.induction.check_inductive(model, invariant, domain, *, k=1)` implements exactly this, for the part
of the problem that is **decidable by enumeration**. An SMT solver makes "for all states `s`" tractable by
symbolic reasoning; we make it tractable, soundly, by quantifying over a **caller-supplied finite
`domain`** — every assignment of the state's bounded variables. Enumeration is a complete decision
procedure for that fragment: "no state in the domain falsifies the step" is a real proof, and any failure
is a concrete counterexample. This is the same "prove ∀ = fail to refute ∃¬" a solver runs, minus the
theory reasoning that handles infinite domains.

Two things make it more than `check`:

- The `domain` **must include unreachable states**. 1-induction over only the reachable set is trivially
  true for any model that already passes `check` (a reachable state's successors are reachable, hence
  satisfy `I`), so it proves nothing new. Quantifying over the full bounded space is what turns it into an
  inductive proof, and it is what surfaces a counterexample-to-induction sitting on an unreachable state.
- `k > 1` proves invariants that are true but not 1-inductive, exactly when the 1-step counterexample is a
  spurious unreachable state that `k` consecutive `I`-states rule out.

The step only ever follows **enabled** transitions, so a partial `apply` protected by its guard is never
called out of bounds (the same care `invariant_coverage` takes when it deliberately applies guarded-off
actions).

## Where it stops, and why that boundary is honest

`check_inductive` needs a finite `domain` to enumerate. It does **not**, on its own:

- prove an **infinite value domain** (an unbounded integer counter) — there is nothing finite to
  enumerate; a sound proof there needs a symbolic decision procedure (a real SMT solver over integer
  arithmetic), which musil does not embed and will not hand-roll (a subtly-unsound solver would "prove"
  false things, the failure mode this codebase refuses);
- prove an **unbounded number of components** (arbitrary N tiles/processes) — that is parameterized
  verification, needing a cutoff theorem or symbolic reasoning about N, again beyond enumeration.

For those, the enumerable `check_inductive` is a bounded refutation: run it over as large a finite domain
as is affordable to *find* counterexamples-to-induction, but it proves the invariant only over the domain
you enumerate. Reasoning past that boundary is a separate, optional symbolic engine (a `z3`-backed extra),
kept out of the dependency-free core. Until then the sound partial answers remain: bounded `check`,
`state_space_metrics` / `solution_cardinality` to judge scope adequacy, and symmetry reduction
(`canonical_by_*`, gated by `symmetry_reduction_sound`) to push the affordable domain higher.
