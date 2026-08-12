---
title: Decide whether probabilistic (DTMC/MDP) checking belongs in musil at all
status: open
area: metrics
owner: null
filed: 2026-08-12
scope: L
verify: inspect
---

Source: gitlab.com/jorgeecardona/musil issue #2 (item 3 of four), filed 2026-08-12. Filed here as a decision, like the Hypothesis item from #1, because the cost is to what musil *is* rather than to a module.

## MEASURED (in this repo)

- `sim.py` draws loss and duplication per message from a seeded RNG ([src/musil/sim.py:40-56](../../src/musil/sim.py#L40-L56), [src/musil/sim.py:305-327](../../src/musil/sim.py#L305-L327)) and `simulate` runs one pass per seed ([src/musil/sim.py:519](../../src/musil/sim.py#L519)). Its own docstring calls it "bug *finding*, not proof" ([src/musil/sim.py:7](../../src/musil/sim.py#L7)). The upstream issue is right that this is sampling, not verification.
- Nothing anywhere computes a probability. `grep -rniE "probab|markov|dtmc|mdp|expected.(steps|cost|reward)" src/` finds only the `sim` docstrings describing per-message draws.
- Everything in `core.py` is exact and integral: `check` returns a boolean verdict with a witness trace, never a number with an error bound.

So the gap is real and correctly described. The question is whether musil should close it.

## The argument against, stated plainly

1. **It is a different kind of answer.** Every result musil produces today is a verdict plus a witness: `INVARIANT VIOLATED` with the shortest trace, `LIVENESS VIOLATED` with a lasso. `P(eventually bad) = 0.0094` has no witness and no shortest anything. Value iteration converges to a tolerance, so the output carries numeric error — a concept that appears nowhere else in the package and that every existing docstring's notion of "proved" would have to be qualified against.
2. **Pure-Python value iteration is slow where it matters.** Fine on the toy models in `tests/`; the models that need probabilities are the large ones, and that is exactly where iterating a transition matrix in Python loses. "numpy optional" is the obvious escape and it reopens, for a much heavier dependency, the same question already deferred in [[12-08-2026-decide-whether-musil-takes-an-optional-hypothesis-dependency-before-building-a-strategy]].
3. **PRISM and Storm exist and are good.** Being worse at their job is not obviously better for musil's users than pointing at them. The reverse is not true — nothing else does what `check` does with the ergonomics musil has.

## The argument for

Stochastic designs are real, and a user who has already written a musil `Model` would rather add weights than re-express it in the PRISM language. If the answer is yes, the honest shape is a *separate* `Model` variant with weighted actions, never weights bolted onto the existing `Action`, so the exact core stays exact.

## Done

A recorded decision — CHANGELOG, README, or a design note — saying either:

- **no**, with the reasoning, and README naming PRISM/Storm for the question so users are pointed somewhere real rather than left to assume musil will grow it; or
- **yes**, in which case the decision must also name: whether numpy becomes an optional extra, what tolerance the iteration reports, and how a probabilistic result is rendered so it cannot be mistaken for a proof.

Observation that will be true either way: someone reading the README can tell, without asking, whether musil intends to answer quantitative questions.

`verify: inspect` — the artifact is the recorded decision.

## Deliberately NOT doing

- **Not prototyping first.** A working DTMC prototype answers the design question by fait accompli, which is the wrong order when the cost is to the package's identity rather than to a module.
- **Not treating `sim`'s probabilities as a head start.** They are per-message draws inside a simulator, not a transition matrix; nothing there is reusable for an exact computation.