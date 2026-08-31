# General probabilistic LTL — designed (LDBA), deliberately deferred

`probability_ltl` is EXACT and complete for every LTL operator applied to STATE predicates — `F`, `X`, `G`,
`GF`, `FG`, and the binary `a U b` / `a R b` / `a W b` — because each of those has a direct characterisation
as (constrained) reachability, a one-step push, or a BSCC/MEC query, with no automaton (see
`PROBABILISTIC_NOTES.md`). What remains needs a deterministic automaton for the formula:

- operands that are THEMSELVES temporal — `X(F a)`, `(F a) U b`, `G(a → X b)`;
- boolean combinations of temporal formulas — `F a ∧ F b`, `(G a) ∨ (F b)`;
- `leadsto` as a quantitative measure.

This note records how to build that engine, the one non-obvious decision (LDBA, not Safra), the soundness
argument, and an incremental, differential-tested build plan. It is the plan; the build is a separate,
multi-tick effort that must stay green each tick.

## Why a plain Büchi automaton is not enough

The qualitative engine (`check_ltl`) is sound with a NONDETERMINISTIC Büchi automaton: it asks whether the
product of the model and the automaton for `¬φ` has ANY accepting run (a `∃` question, decided by
nested-DFS / SCC emptiness — `GeneralizedBuchi.from_ltl`, `_gpvw`). Probability is a `Σ` (measure) question,
and a nondeterministic automaton has no well-defined measure on the product: the same model run can be
accepted along one automaton branch and rejected along another, so `P(φ)` is not the reachability of the
accepting set in `model ⊗ NBA`. The automaton must be DETERMINISTIC on the model's runs (one automaton run
per model run) for the product to be a Markov chain again.

## Why LDBA, not Safra/Rabin

Full determinization of a Büchi automaton needs Safra's construction (→ deterministic Rabin), which is
intricate (Safra trees, node relabelling) and error-prone — exactly what the dependency policy's "build
in-house, keep it a readable reference" spirit wants to avoid. For QUANTITATIVE model checking a weaker object
suffices: a **limit-deterministic Büchi automaton (LDBA)** — deterministic *in the limit*. Result
(Courcoubetis–Yannakakis; Hahn et al. 2015; Sickert et al. 2016): a *suitable* LDBA (deterministic in its
accepting component, at most one nondeterministic "guess" transition into it) gives the CORRECT probability on
a DTMC/MDP product, and is far smaller and simpler to construct than a Safra DRA. LDBA is the modern choice
for probabilistic LTL (it is what Storm/PRISM-games use via `Rabinizer`/`ltl2ldba`). So: **build an LDBA, not a
DRA.**

## The construction

1. **LTL → NBA** — reuse the GPVW front-end: `GeneralizedBuchi.from_ltl(φ)` then degeneralise the generalized
   acceptance to a single Büchi set (the standard counter/degeneralisation; a small `GeneralizedBuchi → Buchi`
   helper — `Buchi` already exists). Front-end is done; this is glue.
2. **NBA → LDBA (suspension / breakpoint construction)** — two parts joined by a guessing jump:
   - **Initial part** `Q₁`: a deterministic *subset* construction over the NBA states (powerset of reachable
     NBA states under the model's labels). No acceptance here.
   - **Accepting part** `Q₂`: at any point the automaton may nondeterministically JUMP from a subset `S ∈ Q₁`
     to a single NBA state `q ∈ S` it "commits" to, then runs the NBA DETERMINISTICALLY from `q` restricted to
     accepting behaviour (a breakpoint construction tracking `(current, owed-accepting)` so the accepting set
     is visited infinitely often). `Q₂` is deterministic; the only nondeterminism is the single jump.
   - This is the "suitable LDBA" shape: the accepting component is deterministic, so on the product it defines
     a Markov chain whose accepting BSCCs/MECs carry the measure.
3. **Product** `model ⊗ LDBA` — state `(s, ℓ)` where `ℓ` is the LDBA state; the model supplies the
   probabilities (DTMC distribution or MDP moves), the LDBA supplies the (mostly deterministic) label
   transition. The guessing jump becomes a scheduler/measurable choice — handled by the accepting-component
   analysis, not by branching the probability.
4. **Accepting analysis + reachability**:
   - **DTMC** — decompose the product into BSCCs (reuse the existing BSCC decomposition). A BSCC is
     ACCEPTING iff it lies in the deterministic accepting part and visits the LDBA's accepting set. `P(φ)` =
     `Σ` reach-probability from the initial product state to the accepting BSCCs (reuse the linear solve).
   - **MDP** — accepting MAXIMAL END COMPONENTS (reuse `_maximal_end_components`): a MEC is accepting iff the
     scheduler can, within it, satisfy the LDBA acceptance (visit the accepting set infinitely often while
     staying). `P_max(φ)` = max reachability to the accepting MECs; `P_min` via the temporal dual
     `P_min(φ) = 1 - P_max(¬φ)` (determinise `¬φ`).

## Soundness argument

The LDBA is *suitable*: its accepting component is deterministic, so `model ⊗ LDBA` restricted to that
component is a genuine Markov chain (DTMC) / MDP, and the set of runs of `model` satisfying `φ` has the SAME
measure as the set of product runs whose projection is accepting — this is the Courcoubetis–Yannakakis /
Sickert et al. correctness theorem for *suitable* LDBAs, the property the construction in step 2 is built to
guarantee (a single jump into a deterministic accepting part). A plain NBA fails exactly here (multiple
accepting runs per model run → no well-defined measure). The engine is only as sound as "suitable" is
enforced, so the construction MUST be tested to preserve the language of the NBA and to keep the accepting
part deterministic.

## Reuse — this is mostly assembly of existing parts

- LTL → NBA: `GeneralizedBuchi.from_ltl` / `_gpvw` (`ltl.py`) — done.
- BSCC decomposition, MEC (`_maximal_end_components`), stay-within, the exact reachability linear solve and MDP
  policy iteration: all in `probabilistic.py` — the accepting analysis is a thin acceptance predicate on top.
- The genuinely NEW code is step 2 (NBA → LDBA) and the product wiring.

## The built-in differential oracle

The engine must **agree with the shipped reductions** on the whole state-predicate fragment: for random
models and random state predicates, `probability_ltl(F/X/G/GF/FG/U/R/W …)` via the new automaton engine must
equal the current direct-characterisation answer (exactly as `test_core_ltl_properties` validates the
qualitative Büchi engine against its reductions). That is a strong, free oracle over the parts we already
trust. On top, corpus known-verdicts for genuinely-nesting formulas with hand-computable probabilities, e.g.
`P(F(a ∧ X b))` on a small chain, `P(F a ∧ F b)`, `P(G(a → X b))`.

## Incremental build plan (each a guarded tick)

1. **[DONE]** `GeneralizedBuchi.degeneralize() → Buchi` — the counter construction, tested (corpus + a
   random-model property test) that the Büchi accepts the same ω-language as the generalized one on the model
   (qualitative, reuses the existing emptiness check). Pure automata transformation, no probability.
2. NBA → LDBA construction, as a pure automaton transformation, tested on finite lasso words (does the LDBA
   accept exactly the NBA's ω-language on the model's label alphabet?) and checked "suitable" (accepting part
   deterministic).
3. DTMC engine: product + accepting-BSCC reachability; wire into `probability_ltl` behind the existing
   `NotImplementedError` fall-through. Land the differential oracle vs the reductions first (must stay green),
   then the nesting known-verdicts.
4. MDP engine: accepting-MEC max reachability + the min dual.

If any tick cannot keep the differential green, STOP and note — a wrong probability is worse than a
`NotImplementedError`.

## Scope / deferral

Bounded, exact, no dependency, no `z3` — same envelope as the rest of the layer (it inherits the enumeration
limitation: the product is finite only for bounded models). CTL / branching-time stays out of scope (not in
the roadmap; `reaches` already covers the headline `AG EF`). This is the LAST substantive piece of the
probabilistic layer; everything else shipped.
