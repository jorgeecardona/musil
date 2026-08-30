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
- **MDP MIN reachability** — `reach_probability_mdp(..., optimize="min")`. Same policy iteration, minimizing,
  with ONE precomputation: `_s0_min` finds the states from which a scheduler can avoid the target forever —
  the greatest set `U` of non-target states in which every state has a move whose support stays inside `U`
  (an absorbing/empty move stays trivially) — by iterative removal, and pins them to 0. That precomputation
  is exactly what makes min exact:
  - **Why min needs it and max does not.** Without it, min policy iteration stalls: a state whose only way
    to 0 is a self-loop (or a loop through a non-target *end component*) keeps, under the current
    evaluation, a move-value equal to its current value, so the strict-improvement step never lowers it to
    the true 0. Pinning `S0min` to 0 up front removes those states from the iteration.
  - **Why the rest is then exact.** No set of the remaining "unknown" states can be closed under any policy
    — a closed unknown set would satisfy the `S0min` staying-condition and so would have been removed as
    `S0min`. Hence every policy reaches `target ∪ S0min` almost surely from every unknown (every policy is
    *proper*), the induced-DTMC linear systems are non-singular, and minimizing policy iteration converges
    to the unique `xmin` in finitely many strictly-decreasing steps.

  This is the graph-theoretic `S0min` (`_s0_min` is an OR-reachability iterative removal, not a full
  alternating attractor game — sufficient here because `S0min` for reachability is "∃ a staying move",
  which is a plain greatest-fixpoint over the move relation) plus the exact rational solve, no maximal
  end-component *collapse* needed: `_dtmc_values` already assigns 0 to unknowns that a fixed policy cannot
  route to the target, so end components are handled by pinning `S0min`, not by quotienting the graph.
  Corpus pins three known verdicts: the two-gamble MDP (`xmin = 1/2`, the worse coin), a self-loop
  (`xmin = 0` where `xmax = 1`), and a two-state non-target end component (`xmin = 0`, the case `_s0_min`
  exists for).
- **Step-bounded reachability** — `steps=k` on either function (`reach_probability`, `reach_probability_mdp`).
  The exact probability of reaching the target WITHIN `k` transitions, by a finite backward induction
  (`_bounded_values`): `V_0` is the indicator of the target, `V_i(s) = opt_move sum P(s') V_{i-1}(s')`. No
  fixed point, so it is exact by construction and needs no `S0` precomputation (a bounded horizon cannot
  stall). `steps=0` is the indicator of the target; a DTMC is the single-move case. Corpus pins the
  geometric law `P(reach within k) = 1 - (1/2)^k` for a fair coin loop.
- **DTMC expected reward** — `expected_reward(model, target, cost=...)`. The expected accumulated cost to
  first reach the target (default unit cost = expected number of steps), solving `E(target) = 0` and
  `E(s) = sum_s' P(s, s') (cost + E(s'))` exactly over the rationals. Finite only when the target is reached
  ALMOST SURELY, so it guards on `reach_probability == 1` from the initial state and raises otherwise (the
  expectation is infinite). The guard is what makes the `(I - P)` system on the non-target states
  non-singular: every explored state is init-reachable, and if init reaches the target a.s. then so does
  every non-target state (a transient state that failed with positive probability would drag init's reach
  probability below 1). Corpus pins the fair-walk absorption time `E = i(N-i)` and the geometric mean `1/p`.

## Deferred (future layers, not blocking)

- **MDP expected reward** (min/max expected cost to reach the target — the stochastic shortest/longest path
  problem). Harder than the DTMC case and than MDP reachability: MAX expected cost is infinite whenever any
  scheduler can loop away from the target with positive probability (so it needs the "all schedulers
  proper" check, not just `S0`), and MIN expected cost (SSP) needs a *proper* initial policy and care with
  zero-cost cycles for policy iteration to converge. Its own increment, with a corpus that includes a
  zero/near-zero-cost cycle so the proper-policy handling is actually exercised. Until then `expected_reward`
  is DTMC-only.
- **Probabilistic LTL / long-run (steady-state) properties.** These reuse the LTL engine and the DTMC/MDP
  machinery but are a larger design; not started.

## References

- Baier & Katoen, *Principles of Model Checking*, ch. 10 (DTMC/MDP reachability, the three-way split,
  maximal end components, value/policy iteration).
- de Alfaro, *Formal Verification of Probabilistic Systems* (PhD thesis, 1997) — end components.
