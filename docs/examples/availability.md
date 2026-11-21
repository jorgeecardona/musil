# Availability: steady-state, until, and recovery cost

**What this teaches:** the probabilistic layer answers more than "will it reach the target?". Over a
system that runs forever it answers *what fraction of time* it is healthy (steady state), *the
probability of one outcome before another* (a constrained "until"), and *the best and worst expected
cost* of a recovery strategy (an MDP). All exact, as `fractions.Fraction`, with no floating-point
error and no dependency.

## The model

A replicated service cycles through health states forever: mostly HEALTHY, occasionally DEGRADED,
sometimes FAILED, then restarting. As a DTMC (each state's enabled actions' weights normalise into a
distribution):

- HEALTHY → HEALTHY with probability 3/4, → DEGRADED with 1/4 (the `stay` action is weighted 3 to
  `degrade`'s 1).
- DEGRADED → HEALTHY or → FAILED, 1/2 each.
- FAILED → DEGRADED (restart).

The chain is irreducible: it never settles into one state, so its steady state is a genuine long-run
average.

## Steady-state availability: `long_run_probability`

The long-run fraction of time in each state is the chain's stationary distribution. Solving `π P =
π`, `Σ π = 1` exactly gives `π(HEALTHY) = 4/7`, `π(DEGRADED) = 2/7`, `π(FAILED) = 1/7`:

```python
long_run_probability(AVAILABILITY, at(HEALTHY), weight=weight)  # 4/7  — availability
long_run_probability(AVAILABILITY, at(FAILED), weight=weight)   # 1/7
```

This is exact even though `Pⁿ` never converges (a periodic chain would still give the right
time-average, the Cesàro limit). Transient states carry zero long-run measure.

## Until-probability: `reach_probability(..., avoid=...)`

Plain reachability says the service reaches FAILED eventually with probability 1 (it keeps cycling).
The more useful question is the probability of FAILING *before* recovering. The constrained (until)
probability `P(¬healthy U failed)` from DEGRADED:

```python
reach_probability(AVAILABILITY, at(FAILED), weight=weight)                    # 1    — eventually, a.s.
reach_probability(AVAILABILITY, at(FAILED), weight=weight, avoid=at(HEALTHY)) # 1/2  — before recovering
```

An `avoid` state that is not the target becomes an absorbing failure, so a run that recovers to
HEALTHY first does not count. From DEGRADED the only way to FAILED without touching HEALTHY is the
direct `fail` edge: 1/2.

## Recovery cost: `expected_reward_mdp(..., optimize=...)`

When recovery is a *choice* between STAGED (cheap, one hop through a recovering state) and DIRECT
(dearer, immediate), the system is an MDP, and both the cheapest and the most expensive strategy
matter:

```python
expected_reward_mdp(RECOVERY, at(HEALTHY), moves=by_strategy, cost=cost, optimize="min")  # 2  — staged (1+1)
expected_reward_mdp(RECOVERY, at(HEALTHY), moves=by_strategy, cost=cost, optimize="max")  # 3  — direct
```

`min` is the stochastic shortest path (a proper policy must exist); `max` is the stochastic longest
path, finite here because every strategy reaches HEALTHY almost surely.

## Source

```python
--8<-- "examples/availability.py"
```

## Run it

```
python examples/availability.py
```

## See also

- [Lossy retry](../textbook.md): the reachability / bounded / expected-cost side of the same layer.
- [API reference](../api.md): `long_run_probability`, `reach_probability`, `expected_reward_mdp`.
