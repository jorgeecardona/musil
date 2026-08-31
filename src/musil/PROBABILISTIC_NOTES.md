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
- **MDP MIN expected reward** — `expected_reward_mdp(model, target, moves=..., cost=...)`. The minimal
  expected accumulated cost over all schedulers (the stochastic shortest path). The piece that is normally
  hard — a *proper* initial policy for policy iteration — comes for free: the max-reachability-optimal
  policy reaches the target almost surely from every state whose max reachability is 1 (a convex combination
  of values `<= 1` equal to 1 forces every successor to 1), so it is proper there and seeds the iteration.
  The iteration then minimises expected cost over the moves whose successors are all proper (`_safe`), each
  evaluation an exact rational solve of `E(s) = cost(s) + sum_s' P(s, s') E(s')`; strict improvement keeps
  the policy proper (an improper policy has infinite cost, never an improvement) and terminates at the
  optimum (Bertsekas & Tsitsiklis SSP). Costs MUST be positive (default unit), so a scheduler that fails to
  reach a.s. has infinite cost; the guard raises when `max reachability(init) != 1`. Corpus pins the
  retry-until-success minimal expected attempts `1/p`.

- **MDP MAX expected reward** — `expected_reward_mdp(..., optimize="max")`. The maximal expected accumulated
  cost over all schedulers (the stochastic LONGEST path). Finite only when EVERY scheduler is proper —
  otherwise a scheduler loops away from the target forever and the max is infinite — so the guard is MIN
  reachability `= 1` from the initial state (the existing `_s0_min` + minimizing `_reach_policy_iteration`),
  which implies min reachability 1 from every reachable state and hence every policy proper. With every policy
  proper, any policy is a valid seed (move 0) and the `_safe` restriction is trivially satisfied; maximizing
  policy iteration (each switch strictly RAISES a bounded, monotone expected cost) converges to the optimum
  over the finite policy space (Bertsekas & Tsitsiklis SSP, the all-proper case). Shares the min path's exact
  rational evaluation `E(s) = cost(s) + sum_s' P(s,s') E(s')`. Corpus pins a fast-vs-slow MDP (`min = 1`,
  `max = 2` steps) and the infinite guard (a self-loop `stall` move drops min reachability below 1, so max
  raises while min stays 1).

- **DTMC long-run / steady-state** — `long_run_probability(model, target, weight=...)`. The exact fraction
  of time the DTMC spends in the target set in the limit (PRISM's steady-state / S operator). A finite DTMC is
  absorbed almost surely into a bottom SCC (BSCC); inside each BSCC — a finite irreducible chain — the long-run
  fraction of time in a state is its stationary probability. So the answer is `sum_B reach(B) * sum_{s in B,
  target(s)} pi_B(s)`: BSCCs via the proven `tarjan`, reachability to each BSCC via the exact `_dtmc_values`,
  and `pi_B` the exact stationary solve (`_stationary`: `pi P = pi`, `sum pi = 1`, one balance row replaced by
  normalization, Gauss-Jordan). This equals the time average even for a PERIODIC BSCC (the Cesàro limit),
  where `P^n` does not converge. Transient states carry zero long-run measure; a deadlock/absorbing state is
  its own BSCC with mass 1. Corpus pins the periodic 2-cycle (`1/2`), a biased chain (`pi(A) = 1/3`), and a
  transient split into two absorbing BSCCs (`1/2`, and `1` for the whole absorbing set).

## Deferred (future layers, not blocking)

- **Zero/negative-cost SSP.** The positive-cost SSP assumption both directions rest on breaks with zero- or
  negative-cost cycles (an improper policy no longer has infinite cost, so policy iteration can stall). Its own
  increment; needs a corpus case that actually exercises the degenerate zero-cost cycle.
- **Probabilistic LTL, and MDP steady-state.** Probabilistic LTL (the probability that a run satisfies a
  temporal formula) reuses the LTL engine and the DTMC/MDP machinery but is a larger design; not started. The
  DTMC long-run above does NOT yet cover the MDP case (min/max long-run over schedulers, which needs maximal
  end components, not just BSCCs); its own increment.

## References

- Baier & Katoen, *Principles of Model Checking*, ch. 10 (DTMC/MDP reachability, the three-way split,
  maximal end components, value/policy iteration).
- de Alfaro, *Formal Verification of Probabilistic Systems* (PhD thesis, 1997) — end components.
