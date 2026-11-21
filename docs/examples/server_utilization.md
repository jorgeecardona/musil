# Server utilisation: steady-state rates, warm-up, and the best/worst policy

**What this teaches:** many questions about a running system are about RATES, not one-off
probabilities. The fraction of time busy, the revenue per step, the throughput. musil computes these
exactly (as `fractions.Fraction`) at three levels: the steady-state average, the transient warm-up
toward it, and the best/worst rate a scheduler can achieve.

## The model

A server is BUSY or IDLE. From IDLE a job arrives or not (1/2 each). From BUSY it finishes or keeps
working; in the ECO regime `work` is weighted 3 to `finish`'s 1, so it stays busy with probability
3/4.

## Steady-state rate: `long_run_reward`

The long-run average of a per-state reward. With the reward = 1-when-BUSY it is the UTILISATION;
with a revenue reward (BUSY earns 10, IDLE costs 1) it is the revenue rate:

```python
long_run_reward(ECO, lambda s: 1 if s.busy else 0, weight=weight)      # 2/3  — utilisation
long_run_reward(ECO, lambda s: 10 if s.busy else -1, weight=weight)    # 19/3 — revenue per step
```

`long_run_reward` weights each bottom-SCC's stationary distribution by the probability of being
absorbed into it; a reward may be negative (a net cost rate).

## The warm-up: `transient_distribution`

The steady state is the limit; before it, the server is warming up. `transient_distribution` gives
the exact distribution after exactly *k* steps, so `P(BUSY at step k)` starting from IDLE climbs
toward 2/3 without being there yet:

```python
[transient_distribution(ECO, k, weight=weight)[Server(True)] for k in range(5)]
# 0, 1/2, 5/8, 21/32, 85/128  ->  2/3
```

This is the point-in-time distribution, distinct from the steady-state limit and from within-k
reachability.

## Best and worst policy: `long_run_reward_mdp`

Suppose the operator can also run BUSY in a TURBO regime (finish and work equally likely, freeing
the server faster). Now the system is an MDP (a policy chooses ECO or TURBO at each busy step) and
the question is the best and worst long-run utilisation over all policies:

```python
long_run_reward_mdp(SERVER_MDP, util, moves=modes, weight=weight, optimize="max")  # 2/3 — ECO keeps it busier
long_run_reward_mdp(SERVER_MDP, util, moves=modes, weight=weight, optimize="min")  # 1/2 — TURBO frees it faster
```

`long_run_reward_mdp` is the exact reference oracle: a finite MDP has an average-optimal memoryless
deterministic policy, so it takes the extreme of `long_run_reward` over those policies. Exact, for
small MDPs.

## Source

```python
--8<-- "examples/server_utilization.py"
```

## Run it

```
python examples/server_utilization.py
```

## See also

- [Availability](availability.md): steady-state *probabilities* and until-probabilities on a DTMC.
- [API reference](../api.md): `long_run_reward`, `transient_distribution`, `long_run_reward_mdp`.
