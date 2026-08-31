# Gambler's ruin — the canonical random walk, exact

**What this teaches:** the textbook absorbing random walk gives three classical closed forms, and
`musil.probabilistic` returns each one *exactly* as a `fractions.Fraction`. A gambler starts with `i` chips,
bets one at a time on a coin, and stops at ruin (0 chips) or at the goal `N`.

## The model

A 1-D walk between two absorbing barriers — `up` and `down` are enabled only strictly between them:

```python
Model(
    init=Walk(start),
    actions=[
        Action("up",   enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos + 1)),
        Action("down", enabled=lambda s: 0 < s.pos < n, apply=lambda s: Walk(s.pos - 1)),
    ],
    terminal=lambda s: s.pos in (0, n),  # 0 = ruin, n = goal, both absorbing
)
```

## Reaching the goal — `reach_probability`

=== "Fair coin — `i / N`"

    ```python
    reach_probability(walk_model(i, N), goal)  # Fraction(i, N)
    ```

    With a fair coin the position is a martingale (a fair game), so the probability of reaching `N` before
    `0` is **linear in the stake**: exactly `i / N`. For `N = 5` the starts `0..5` give `0, 1/5, 2/5, 3/5,
    4/5, 1`.

=== "Biased coin — `(1-(q/p)^i)/(1-(q/p)^N)`"

    ```python
    reach_probability(walk_model(2, 5, up=2, down=1), goal,
                      weight=lambda name, s: 2 if name == "up" else 1)  # Fraction(24, 31)
    ```

    Weighting the up-step `2 : 1` makes `p = 2/3`, so `q/p = 1/2`. The goal probability from `i = 2` of
    `N = 5` is `(1 - (1/2)²) / (1 - (1/2)⁵) = (3/4)/(31/32) = 24/31`. Weights are integer ratios; the layer
    normalises them into the exact distribution.

## Expected duration — `expected_reward`

Charge 1 per bet and the expected reward *is* the expected number of bets until the game ends. For the fair
walk it is exactly `i * (N - i)`:

```python
expected_reward(walk_model(i, N), absorbed, cost=lambda name, s: 1)  # Fraction(i * (N - i))
```

For `N = 5` the starts `0..5` give `0, 4, 6, 6, 4, 0` — longest from the middle, as intuition expects. The
walk is absorbed almost surely, so the expectation is finite (a stochastic-shortest-path answer).

??? note "Why `i / N` (the martingale argument)"

    Let `h(i)` be the probability of reaching `N` before `0` from `i`. For the fair walk each step goes up or
    down with probability 1/2, so `h(i) = ½ h(i+1) + ½ h(i-1)`, with `h(0) = 0` and `h(N) = 1`. That
    recurrence forces `h` to be **linear**, and the only line through `(0, 0)` and `(N, 1)` is `h(i) = i / N`.
    musil does not use this formula — it solves the DTMC's linear system over `Fraction` — so the test that
    `reach_probability` equals `i / N` is an independent check of the exact solver.

## Source

```python
--8<-- "examples/gamblers_ruin.py"
```

## Run it

```
python examples/gamblers_ruin.py
```

## See also

- [Monty Hall](monty_hall.md) — another exact-fraction DTMC, the famous 2/3 result.
- [Availability](availability.md) — steady-state, until-probabilities, and MDP recovery cost.
- [API reference](../api.md) — `reach_probability`, `expected_reward`, `assert_probability`.
