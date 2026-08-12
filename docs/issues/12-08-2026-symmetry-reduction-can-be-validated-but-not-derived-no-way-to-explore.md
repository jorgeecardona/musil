---
title: "Symmetry reduction can be validated but not derived: no way to explore modulo a permutation group"
status: open
area: core
owner: null
filed: 2026-08-12
scope: L
verify: test
---

Source: gitlab.com/jorgeecardona/musil issue #1 (item 2 of five), filed 2026-08-11 from adopting musil in the thalamus classifier workspace.

## MEASURED (in this repo)

- `check` and `explore` accept `canonicalize: Callable[[S], S] | None` — [src/musil/core.py:149-166](../../src/musil/core.py#L149-L166) and [src/musil/core.py:257-266](../../src/musil/core.py#L257-L266). The caller must write the canonical form by hand; nothing in the package builds one.
- `symmetry_reduction_sound(model, canonicalize)` — [src/musil/core.py:392-424](../../src/musil/core.py#L392-L424) — only *grades* a canonicalizer the caller already wrote, and it does so by exploring the model **fully** first ([src/musil/core.py:414](../../src/musil/core.py#L414)). So the validation gate is only usable on instances small enough not to need reduction.
- `grep -rn "permutation\|orbit\|quotient" src/` returns 0 hits.

The asymmetry is the finding: musil can tell you a symmetry reduction is sound, but cannot give
you one, and cannot validate one at the size where you need it.

## REPORTED (from the adopting workspace, not verifiable here)

Two models are blocked on this. The artifact-promotion reconciler has 24 interchangeable routes;
the EFS-sync model has N interchangeable boxes. Full exploration is factorial in identities that
provably do not matter. The workaround adopted there is small-scope — model 3 routes and argue by
symmetry in prose — which is exactly the doubt a checker is supposed to remove.

## Done

A helper that takes a group of state permutations and returns a `canonicalize` for it — the natural
shape being `canonical_by_permutations(perms)` where `perms` is generated from a set of
interchangeable identities, returning `min` over the orbit under a total order on states. Observation
that will be true: for a model with N interchangeable components, `explore(model, canonicalize=...)`
reports `states_explored` smaller than the unreduced run by roughly N! for N in {3, 4, 5}, AND
`symmetry_reduction_sound(model, that_canonicalize)` returns True for the N where the full run is
still affordable. Both numbers in one test, so the saving and the soundness are one claim.

The orbit-minimum construction is exponential in the group if done naively over all N! permutations;
generating from transpositions and canonicalizing componentwise (sort the per-identity slices) is the
practical form. Which one this ships is a design question inside the issue, not a separate issue.

`verify: test` — the claim is a state count and a boolean from `symmetry_reduction_sound`, both
computable in-process.

## Deliberately NOT doing

- **No partial-order reduction.** REDUCTION_NOTES.md already records why it is deferred, and the
  upstream issue ranks symmetry above it for these models. Filing POR here would re-open a settled
  decision.
- **Not making reduction automatic.** `canonicalize` stays opt-in with soundness as the caller's
  obligation, exactly as [src/musil/core.py:159](../../src/musil/core.py#L159) states. Silently reducing a
  model the user did not declare symmetric is how a checker returns a green result for a question
  nobody asked.
- **Not fixing `symmetry_reduction_sound`'s full-exploration requirement.** It is inherent — the full
  run *is* the trusted reference. Validate small, then trust large, is the intended workflow and
  should be documented rather than engineered away.