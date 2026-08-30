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
- [x] GPVW construction (`GeneralizedBuchi.from_ltl`), validated by differential agreement with the
      reducible-fragment reductions + hand-verified `Until`/`Next`/nested cases.
- [x] Wire `check_ltl` to `from_ltl(Not(phi)).has_accepting_run(_stutter(explore(model)))` for the
      irreducible fragment; terminal states are stutter-extended. General-LTL corpus entries pinned.
- [x] Counterexample lasso from the engine (`GeneralizedBuchi.accepting_lasso`): a stem to the accepting
      SCC plus a cycle visiting every acceptance set, mapped to model states; `check_ltl`'s engine path now
      returns it as the `Result.trace`.
- [ ] Re-express the fixed liveness forms and `musil.patterns` as sugar over `check_ltl`.
- [ ] Mark the loop start in the trace (the trace is stem + one cycle iteration; there is no explicit
      "cycle repeats from here" marker on `Result` yet).

## Terminal states (must handle when wiring check_ltl)

LTL is over INFINITE runs; the Büchi emptiness only sees infinite product runs. A model with a terminal /
deadlock state has FINITE maximal runs that ending there, which the product simply drops (the product
state has no successor, so it is in no cycle). So `check_ltl` over a model with terminal states must
STUTTER-EXTEND them — add a self-loop on every deadlock/terminal state before building the product — so a
run that would end there instead repeats its last state forever, and `F p` / `G p` get the intended
finite-run semantics. The GPVW tests use only the cycling traffic light (all runs infinite) to keep this
orthogonal; the wiring step owns the stutter extension.

## Soundness discipline

The engine is soundness-critical: a bug means a wrong verdict on a temporal property. Guards:

- The corpus pins known-verdict LTL formulas on classic models; a wrong engine flips one.
- The reducible fragment is the cross-check: for any formula the current reductions handle, the general
  engine must agree with `check`/`check_liveness`. A differential test over generated formulas enforces it.
- Fairness composes as a premise (`fair -> φ`), matching `check_liveness`'s `fair`/`fair_strong`.
- Restrict to the finite reachable graph; the automaton is finite by construction. No infinite/unbounded
  reasoning here (that is the induction/`[smt]` frontier, separate).
