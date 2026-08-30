# Probabilistic layer — shipped vs deferred

`musil.probabilistic` gives EXACT quantitative answers over the reachable graph, as `fractions.Fraction`,
with no dependency (the same Tier-0 discipline as the rest of musil: numpy would only ever be an optional
accelerator for large linear solves, never required).

## Shipped

- **DTMC reachability** — `reach_probability(model, target, weight=...)`. The reachable graph as a
  discrete-time Markov chain: each state's enabled actions' `weight` normalise into a distribution over
  successors. Exact via the three-way split (target -> 1, cannot-reach -> 0, rest solve `(I-P)x=b`) and
  Gauss-Jordan over the rationals (`_solve_linear`, `_dtmc_values`).
- **MDP MAX reachability** — `reach_probability_mdp(model, target, moves=..., optimize="max")`. A
  caller-supplied `moves` partitions each state's enabled actions into the moves a scheduler chooses
  between; actions within a move form one distribution. The maximal reachability probability over all
  schedulers, solved EXACTLY by policy iteration: evaluate a policy as a DTMC (exact rational solve),
  switch each state to a strictly better move under those values, repeat until stable. Terminates because
  each switch strictly increases the (bounded, monotone) values, so no policy repeats and the policy space
  is finite.

## Deferred — MDP MIN reachability (`optimize="min"` raises `NotImplementedError`)

Min-reachability is genuinely harder than max, and getting it subtly wrong returns an unsound quantitative
answer (the worst outcome for a verification tool — same reasoning as the POR deferral in
`REDUCTION_NOTES.md`). Two specific obstacles:

1. **S0min is a game, not plain graph reachability.** For MAX, the probability-0 set is exactly the states
   from which the target is unreachable — plain backward reachability, which `_dtmc_values` already
   computes from the support. For MIN, a scheduler is trying to AVOID the target: `S0min` is the set of
   states from which the min-scheduler can force *never* reaching the target with positive probability.
   That is an alternating (AND/OR) reachability / attractor computation over the MDP graph, not a simple
   BFS.

2. **End components break naive policy iteration.** A min-scheduler can stay forever inside a non-target
   *end component* (a maximal set of states with a scheduler that keeps the play inside it), giving
   probability 0 there. Policy iteration for min can then cycle between equal-value policies, and the
   induced-DTMC linear system is singular on such a component. The sound method first collapses maximal
   end components (Baier & Katoen ch. 10.6 / de Alfaro's thesis), computes `S0min`/`S1min` as games, then
   solves the remainder — or uses value iteration from above (which only converges in the limit, so it is
   not exact over `Fraction`).

Plan when built: implement the maximal-end-component decomposition + the `S0min` attractor game, reusing
Tarjan (already in `liveness.py`) for the SCC/EC work, then the same exact rational solve on the collapsed
graph. Gate it with a known-verdict corpus entry whose min value is hand-computable (e.g. the safe/risky
MDP where `Vmin` picks the risky move) AND with a case that has a non-target end component, so the EC
handling is actually exercised. Until then `optimize="min"` raises with a message pointing here.

## References

- Baier & Katoen, *Principles of Model Checking*, ch. 10 (DTMC/MDP reachability, the three-way split,
  maximal end components, value/policy iteration).
- de Alfaro, *Formal Verification of Probabilistic Systems* (PhD thesis, 1997) — end components.
