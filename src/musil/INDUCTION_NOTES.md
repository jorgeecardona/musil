# Inductive invariants / k-induction — designed, deliberately deferred

`check` is exhaustive **up to a scope** (`max_states`, a small `init`). For a system with unbounded
state — an arbitrary number of tiles, components, or processes — a passing check proves the invariant
only within the modelled scope, and the honest residual doubt is "is the scope enough?". The standard
answer is an **inductive** proof that discharges the invariant without enumerating the reachable set:

- **base**: `I(init)` holds, and
- **step**: for every action `a` and every state `s`, `I(s) ∧ enabled(a, s) ⇒ I(apply(a, s))`.

If both hold, `I` is invariant for **all** reachable states at **any** scope. `k`-induction generalises
the step to `k` consecutive transitions for when 1-induction is too weak.

This note records the design and, more importantly, **why it is not shipped** — the same discipline
`REDUCTION_NOTES.md` applies to partial-order reduction.

## Why it does not fit musil's roadmap

The step quantifies over **every state `s` satisfying `I`** — not the reachable ones, *all* of them,
the unreachable included. That is the whole point of induction: it never builds the reachable set. But
musil is an **explicit-state** checker: it *enumerates reachable states one at a time*. It has no way to
range over "all `s` such that `I(s)`" because it has no symbolic representation of a state set and no
decision procedure to discharge the implication over one. States are opaque Python values and `I`,
`enabled`, `apply` are opaque Python callables; the only thing musil can do with them is *evaluate* them
at a concrete state, which is enumeration, which is exactly what induction exists to avoid.

Doing the step **soundly** therefore needs a symbolic state/predicate language and an SMT/SAT solver to
prove `I(s) ∧ enabled(a, s) ⇒ I(apply(a, s))` as a formula. That breaks two roadmap constraints at once:

1. **dependency-free / pure standard library** — a real discharge needs z3 or equivalent;
2. **explicit-state** — the identity of the tool; a symbolic engine is a different tool.

## The tempting shortcut is unsound, so it is worse than nothing

It is easy to write a `check_inductive` that enumerates the reachable (or scope-bounded) states and
checks the step only over *those*. That does **not** prove the unbounded property. It proves "no
reachable state has an `I`-violating successor" — which, for a passing model, is precisely what `check`
already established within the scope. Returning `PROVEN` from it would claim an unbounded guarantee the
enumeration cannot support: a green answer for a question nobody asked, the exact failure mode musil
rejects everywhere else (the `str`/`bytes` guard, the `canonicalize`/`footprint` soundness gates). A
verification tool that overclaims is worse than one that is merely bounded.

## What WOULD be required to ship it

- a symbolic encoding of states and of `I`/`enabled`/`apply` (an AST or an SMT theory), not opaque
  callables;
- a decision procedure to discharge the step (an optional `z3`-backed extra, clearly separated from the
  dependency-free core);
- on failure, a **counterexample-to-induction** — a state satisfying `I` whose successor violates it —
  so the author *strengthens* `I` rather than trusting a bare `False`;
- output that claims no more than the solver proved (1-induction vs `k`-induction vs bounded).

If built, it is a sibling engine, not a change to the explicit-state core.

## What already fits and attacks the same doubt

The "is the scope enough?" worry has partial, sound answers that ship today:

- **bounded exhaustive `check`** up to a deliberately chosen scope finds shallow bugs fast;
- **`state_space_metrics` / `solution_cardinality`** measure the shape of the explored space so the
  scope choice is informed, not guessed;
- **symmetry reduction** (`canonical_by_sorting` / `canonical_by_permutations` / `canonical_by_fields`,
  each gated by `symmetry_reduction_sound`) pushes the affordable scope far higher by collapsing
  interchangeable identities — often turning "argue by symmetry about N" into "check the quotient".

These do not *close* the unbounded gap; they narrow it honestly. Closing it is the inductive engine
above, and it waits until it can be built without overclaiming.
