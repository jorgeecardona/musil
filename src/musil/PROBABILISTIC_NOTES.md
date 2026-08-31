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
- **Transient (point-in-time) distribution** — `transient_distribution(model, steps)`. The exact state
  distribution `dict[state, Fraction]` AFTER EXACTLY `steps` transitions (PRISM's transient / instantaneous
  analysis), by the forward push `pi_0 = delta_init`, `pi_{i+1}(s') = sum_s pi_i(s) P(s,s')`. Exact, no fixed
  point; an absorbing state keeps its mass. Point-in-time queries (probability in a set AT step k, expected
  reward AT step k) follow by summing over the returned distribution — distinct from `reach_probability(steps=k)`
  (WITHIN k) and from the steady-state limit. Corpus pins the fair-coin loop (`pi_k(done) = 1-(1/2)^k`) and a
  periodic 2-cycle whose point distribution ALTERNATES (all mass on one state), unlike its `1/2` steady state.
- **Step-bounded expected reward** — `steps=k` on `expected_reward` and `expected_reward_mdp`. The expected
  cost accumulated until the target is reached OR `k` steps elapse, by the same finite induction with an
  immediate-cost term: `E_0 = 0`, `E_i(s) = cost(s) + sum_s' P(s,s') E_{i-1}(s')` (DTMC) or optimised over the
  moves (MDP, min/max). Always finite, so unlike the unbounded expected reward it needs NO almost-sure /
  proper-policy guard. Corpus pins the closed form `E_k = 2(1 - (1/2)^k)` for the fair-coin retry loop and the
  bounded min/max cost of a staged-vs-direct recovery MDP.
- **Constrained (until) reachability** — `avoid=` on either function. The probability of the until property
  `P(¬avoid U target)`: reaching the target WITHOUT first entering an `avoid` state. Reuses the existing
  0-sink mechanism exactly — an `avoid` (non-target) state is made absorbing with value 0 (empty distribution
  for the DTMC; the empty move for the MDP, which `_s0_min`/`_dtmc_values`/`_bounded_values` all already
  resolve to 0), and `target` takes precedence. Works unbounded and `steps=k`, DTMC and MDP min/max. Corpus
  pins a DTMC where `avoid` drops reachability from 1 to 1/2 (a state that would eventually reach the target
  a.s. by bouncing, but only reaches it directly with probability 1/2 while avoiding the failure state), and
  an MDP where `avoid` separates the schedulers (min 1 -> 1/2, max stays 1).
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
- **DTMC long-run AVERAGE reward** — `long_run_reward(model, reward, weight=...)`. The exact steady-state
  reward rate (PRISM's `R=? [S]`): in the limit, the mean of `reward(state)` over the run,
  `sum_B reach(B) * sum_{s in B} pi_B(s) * reward(s)` — the same BSCC + stationary machinery as above, with the
  reward in place of the indicator. `reward` MAY be negative (a net cost rate). `long_run_probability` is the
  special case `reward = 1_target` and now DELEGATES to `long_run_reward` (one BSCC loop, no drift). Corpus
  pins a periodic 2-cycle with rates 3/1 (`= 2`) and a transient split with rates 10/2 (`= 6`) and a negative
  rate (`= -1/2`). This is the DTMC average-reward; the MDP long-run average (over schedulers) still needs the
  rational LP noted below.

- **Probabilistic LTL, reducible fragment** — `probability_ltl(model, formula)`. The exact probability that a
  random DTMC run satisfies `formula`, for the shapes with a direct characterisation: `F p` = reachability of
  `p`; `G p` = `1 - P(F ¬p)`; `GF p` = probability of absorption into a bottom SCC that CONTAINS a `p` state (a
  run visits every state of its absorbing BSCC infinitely often); `FG p` = absorption into a bottom SCC
  ENTIRELY inside `p`. Reuses the reachability solve and the BSCC decomposition (`_bscc_reach_sum`), and the
  reducible-fragment matcher from `check_ltl` (`_push_negations` / `_state_predicate`). Corpus separates GF
  from FG on a model with a `{A,B}` cycle where only `A` is the target: `P(GF A) = 1/2`, `P(FG A) = 0`.

- **MDP probabilistic LTL, F / G / GF / FG, max AND min** — `probability_ltl(model, formula, moves=...,
  optimize="max"|"min")`. The optimal probability over all schedulers that a run satisfies `formula`, for the
  reducible fragment, all EXACT and with NO linear programming (that is only for the long-run AVERAGE below):
  - `F p` — max / min reachability (the existing policy iteration; min uses the `_s0_min` precomputation).
  - `G p` — `1 - P_min(F ¬p)` (max), `1 - P_max(F ¬p)` (min).
  - `GF p` (Büchi) — max = max reachability to the states in a MAXIMAL END COMPONENT containing a `p` state
    (reach it, then cycle through `p` forever; `_maximal_end_components` by SCC-refinement, an absorbing state
    its own MEC — consistent with the DTMC deadlock treatment). min = the dual `1 - P_max(FG ¬p)`.
  - `FG p` (co-Büchi) — max = max reachability to the region the scheduler can stay inside `p` forever
    (`_stay_within`, a greatest fixpoint). min = the dual `1 - P_max(GF ¬p)`.

  So the whole fragment rests on three primitives — max/min reachability, MEC (for GF-max), and the
  stay-within set (for FG-max) — plus the standard temporal duals. Corpus pins the full matrix on one model:
  a scheduler that can steer gives `max = 1`, `min = 0` for F/GF/FG (and G ¬Z); a probabilistic coin that
  cannot gives `max = min = 1/2`.

## Deferred (future layers, not blocking)

- **General probabilistic LTL** (`Until`, `Next`, leads-to, nested/ disjoined temporal operators). Unlike the
  qualitative engine, the quantitative measure needs a DETERMINISTIC automaton for the formula — the
  nondeterministic Büchi automaton the GPVW engine builds gives the wrong probability on the DTMC product — so
  it needs a Rabin/Safra determinization (or a limit-deterministic construction), a larger build.
  `probability_ltl` raises `NotImplementedError` outside the reducible fragment until then.
- **Zero/negative-cost SSP.** The positive-cost SSP assumption both directions rest on breaks with zero- or
  negative-cost cycles (an improper policy no longer has infinite cost, so policy iteration can stall). Its own
  increment; needs a corpus case that actually exercises the degenerate zero-cost cycle.
- **MDP long-run AVERAGE reward.** The steady-state *average reward* over schedulers (not the GF probability
  above) needs, within each MEC, the max/min long-run average — a linear program over the rationals (an exact
  rational simplex), a much larger build than the MEC + reachability the GF probability uses.

## References

- Baier & Katoen, *Principles of Model Checking*, ch. 10 (DTMC/MDP reachability, the three-way split,
  maximal end components, value/policy iteration).
- de Alfaro, *Formal Verification of Probabilistic Systems* (PhD thesis, 1997) — end components.
