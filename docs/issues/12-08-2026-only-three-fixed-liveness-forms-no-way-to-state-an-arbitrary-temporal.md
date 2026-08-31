---
title: Only three fixed liveness forms; no way to state an arbitrary temporal property
status: done
area: liveness
owner: null
filed: 2026-08-12
fixed_in: 8786b92
scope: L
verify: test
---

## Resolved (triaged 2026-08-31)

The full LTL layer landed (`musil.ltl`, `fixed_in` names the first commit; completed over subsequent
commits). `check_ltl(model, formula)` states ANY LTL property — `Not`/`And`/`Or`/`Next`/`Until`/`Always`/
`Eventually`/`Release`/`WeakUntil` and nesting — via GPVW → generalized Büchi → product + SCC emptiness, with a
lasso counterexample (`--- loops forever ---`) on failure. This EXCEEDS all three cheap subsets this issue
proposed (caller-supplied automaton / safety-LTL / a couple more seedings).

Critically, the failure mode this issue named — "a half-built LTL layer that accepts formulas it silently
mis-translates" — was avoided by construction: the general Büchi engine is differential-tested against the
proven reductions (`F`/`G`/`GF` forced through the engine equal their reducible forms) over random models and
random predicates (`tests/test_core_ltl_properties.py`), the exact guard this issue demanded. The three fixed
`check_liveness` forms and fairness are untouched and still used where they apply; `patterns` are sugar over the
same engine. `verify: test` is satisfied — properties fail with a lasso and pass after the model is fixed
(corpus + example `ltl_properties.py`). The upstream GitLab issue (#2 item 2) can be closed.

Source: gitlab.com/jorgeecardona/musil issue #2 (item 2 of four), filed 2026-08-12.

## MEASURED (in this repo)

`check_liveness` offers exactly three shapes, selected by keyword ([src/musil/liveness.py:62-96](../../src/musil/liveness.py#L62-L96)):

- default — `<>P` (eventually)
- `everywhere=True` — `[]<>P`
- `leadsto_from=Q` — `always (Q implies eventually P)`

plus `fair` / `fair_strong`. There is no `U` (until), `X` (next), `R` (release), `W` (weak until), no nesting, and no safety-LTL such as `always (p implies next q)`.

What already exists and would be reused: `_tarjan` ([src/musil/liveness.py:188](../../src/musil/liveness.py#L188)), `_fair_admissible` ([src/musil/liveness.py:163](../../src/musil/liveness.py#L163)), `_simple_cycle` ([src/musil/liveness.py:273](../../src/musil/liveness.py#L273)), `_bfs` and `_stem`. The three fixed forms are already implemented as three seedings of one shared ¬P-subgraph analysis ([src/musil/liveness.py:105-150](../../src/musil/liveness.py#L105-L150)).

## The split that matters, and it is not the one the upstream issue draws

The upstream proposal is "a small formula AST checked via the standard automata-theoretic route (product with a Büchi automaton)". That framing hides where the work actually is.

- **The search half is nearly free.** Given a Büchi automaton, the product with `Graph` and the fair-cycle search is the machinery listed above, already written and already tested.
- **The translation half is a project.** LTL → Büchi (LTL2BA / Gerth-Peled-Vardi-Wolper, or the tableau construction) is the part nobody writes in an afternoon, and getting it subtly wrong produces a checker that answers confidently and wrongly — the worst failure mode this repo recognises.

So this issue should not be picked up as one piece. INFERRED, and stated as inference: the cheap useful subset is likely one of

1. accept a caller-supplied automaton (states, transitions labelled by state predicates, accepting set) and do the product — all search, no translation; or
2. safety-LTL only (`[]`, `X`, `->` over a bounded horizon), which is a monitor rather than a Büchi product and needs no SCC search at all; or
3. keep the fixed forms and add the two or three that come up in practice (`U`, `W`) as further seedings of the existing analysis.

Which of those is worth building is not answerable from here — it needs a real property somebody wanted to state and could not.

## Done

Either a landed subset with the property that motivated it named in the CHANGELOG, or a recorded decision that the three fixed forms plus fairness are enough and why. What must NOT happen is a half-built LTL layer that accepts formulas it silently mis-translates.

`verify: test` — whichever subset lands, the evidence is a property that fails with a lasso counterexample and passes after the model is fixed.

## Deliberately NOT doing

- **Not starting with the AST.** Designing `Not/And/Or/Next/Until/Always/Eventually/Release` first commits to the translation being written, which is the expensive half, before anyone has shown a property they needed it for.
- **Not touching the existing three forms** until a general layer is real. They are documented, tested, and correct; making them sugar over an unfinished general path would trade working code for a refactor.
- Blocked on nothing, but it should not be picked up ahead of [[12-08-2026-a-green-check-cannot-say-whether-an-action-was-ever-enabled-or]], which is smaller and pays off immediately.