# LTL engine — plan for the general (Büchi) checker

`musil.ltl` ships an LTL formula AST and `check_ltl`, which today checks the fragment that reduces
SOUNDLY onto the existing proven primitives (`check`, `check_liveness`):

- `G(state)`, `F(state)`, `G F(state)`, `G(a -> F b)`, and their negations (via `_push_negations`),
- and any top-level conjunction of the above (`model |= a & b` iff `model |= a` and `model |= b`).

Everything else — `Until`, `Release`, `Next` in general position, `F G`, disjunctions of temporal
formulas, arbitrary nesting — raises `NotImplementedError` rather than returning a guessed verdict. This
note is the plan for the general engine that will replace those refusals, built incrementally on top of
the same AST, dependency-free (per the dependency policy: no z3, build it ourselves).

## The standard pipeline (what we are building)

`model |= φ` (every run of the model satisfies φ) is checked by the automata-theoretic method:

1. **Negate and normalise.** Work with `¬φ`; a run violates φ iff it satisfies `¬φ`. Put `¬φ` in
   negation normal form (`_push_negations`, done).
2. **`¬φ -> generalized Büchi automaton (GBA)`.** The tricky front half. Two standard routes:
   - **GPVW** (Gerth–Peled–Vardi–Wolper, 1995): on-the-fly tableau expansion of nodes carrying
     `New/Old/Next` obligation sets; one acceptance set per `Until` subformula.
   - **VWAA -> GBA** (Gastin–Oddoux, ltl2ba): very-weak alternating automaton, then co-Büchi
     degeneralization. Smaller automata, more machinery.
   We will implement GPVW first (simpler to get right), tested on its own against known small automata
   (`F p`, `G p`, `p U q`, `G F p`) by comparing accepted/rejected ultimately-periodic words.
3. **Degeneralize GBA -> BA** (counter construction) if we build the product against a GBA directly, or
   keep multiple acceptance sets and use a generalized nested-DFS.
4. **Product with the reachable graph.** The Kripke structure is `explore(model)`; the product state is
   `(model_state, automaton_state)`; a product edge exists when the model transition's target satisfies
   the automaton edge's label (a boolean over atoms evaluated on the model state).
5. **Emptiness via nested-DFS** (Courcoubetis–Vardi–Wolper–Yannakakis): an accepting cycle reachable
   from an initial product state is a run satisfying `¬φ`, i.e. a counterexample to φ. Return it as a
   lasso (stem + cycle) mapped back to model states and actions, so `check_ltl` yields a real trace.

## Sequencing (one guarded increment per step)

- [x] AST + reducible fragment + `_push_negations` + conjunction split.
- [ ] Product + nested-DFS emptiness over a HAND-BUILT automaton data structure (the sound back half),
      tested against known automata on the corpus models. Lower risk; build and trust it first.
- [ ] GPVW `¬φ -> GBA` construction, tested independently (accept/reject ultimately-periodic words).
- [ ] Wire `check_ltl` to `push_negations -> GPVW -> product -> nested-DFS`, replacing the
      `NotImplementedError`s; re-express the fixed liveness forms and `musil.patterns` as sugar over it.
- [ ] Corpus: pin general-LTL verdicts (`p U q`, `X`, `F G`, nested) on the classic models.

## Soundness discipline

The engine is soundness-critical: a bug means a wrong verdict on a temporal property. Guards:

- The corpus pins known-verdict LTL formulas on classic models; a wrong engine flips one.
- The reducible fragment is the cross-check: for any formula the current reductions handle, the general
  engine must agree with `check`/`check_liveness`. A differential test over generated formulas enforces it.
- Fairness composes as a premise (`fair -> φ`), matching `check_liveness`'s `fair`/`fair_strong`.
- Restrict to the finite reachable graph; the automaton is finite by construction. No infinite/unbounded
  reasoning here (that is the induction/`[smt]` frontier, separate).
