# Monty Hall: the 2/3 result, exact

**What this teaches:** a famous, counterintuitive probability comes out *exactly* (`Fraction(2, 3)`
versus `Fraction(1, 3)`) with no sampling and no floating-point error. It also shows a real
modelling decision: Monty Hall is **two DTMCs** (one per strategy), not one MDP, because the player
cannot see where the car is when they decide.

Three doors, a car behind one and goats behind the others. You pick a door; the host (who knows the
layout) opens a *different* door revealing a goat; you may keep your door or switch to the remaining
one. Switching wins with probability 2/3.

## The two strategies

The player's initial pick is fixed at door 1 (the doors are symmetric, so this loses no generality).
Each strategy is a fixed policy, so it is its own DTMC:

=== "Switch: 2/3"

    ```python
    SWITCH = Action("switch", enabled=decision,
                    apply=lambda s: replace(s, final=5 - s.opened))
    reach_probability(SWITCH_GAME, won)  # Fraction(2, 3)
    ```

    Switching wins in exactly the cases where your first pick was a goat, which is 2/3 of the time.

=== "Stay: 1/3"

    ```python
    STAY = Action("stay", enabled=decision,
                  apply=lambda s: replace(s, final=PICK))
    reach_probability(STAY_GAME, won)  # Fraction(1, 3)
    ```

    Staying wins only when your first pick was already the car, which is 1/3 of the time.

## The model, annotated

All the branching is uniform, so no `weight` function is needed. The uniform default *is* the game's
randomness:

```python
def _place(d: int) -> Action[Game]:  # (1)!
    return Action(f"car{d}", enabled=lambda s: s.car == 0, apply=lambda s: replace(s, car=d))

def _open(o: int) -> Action[Game]:  # (2)!
    return Action(f"open{o}",
                  enabled=lambda s: s.car != 0 and s.opened == 0 and o != s.car,
                  apply=lambda s: replace(s, opened=o))
```

1.  Three `car1`/`car2`/`car3` actions, all enabled at the start with equal weight. So the car sits
    behind each door with probability **1/3**. This is the only randomness the player faces.
2.  The host opens a goat door that is neither your pick (door 1) nor the car. When your pick
    *hides* the car, **both** other doors are goats, so `open2` and `open3` are both enabled. A
    uniform **1/2** choice. Otherwise exactly one door qualifies and the host is forced.

## Why a DTMC and not an MDP

!!! info "Observability is the whole point"

    musil's MDP policies are **state-based**, and the state carries `car`. An MDP scheduler could
    therefore read the car's position and pick the winning door every time.
    `reach_probability_mdp(..., optimize="max")` would return `1`, not `2/3`. But the real player
    **cannot see the car** when they decide. Baking the strategy into the model's structure (only
    `stay`, or only `switch`, is ever enabled) encodes exactly that partial observability: the
    choice is fixed in advance and cannot depend on `car`. That is why each strategy is its own
    DTMC.

??? note "The exact derivation (why 2/3)"

    Condition on your first pick (door 1):

    - **You picked the car** (probability 1/3). The host opens either goat. Switching moves you
      *off* the car, so you **lose**; staying **wins**.
    - **You picked a goat** (probability 2/3). The host is forced to open the *other* goat, so the
      remaining door is the car. Switching moves you *onto* the car, so you **win**; staying
      **loses**.

    So `P(win | switch) = 2/3` and `P(win | stay) = 1/3`. They sum to 1 because the car is behind
    either the door you'd keep or the door you'd switch to. Never a third place. musil computes both
    by solving the DTMC's linear system over `Fraction`, so the answers are these exact rationals,
    not `0.6667`.

## Source

```python
--8<-- "examples/monty_hall.py"
```

## Run it

```
python examples/monty_hall.py
```

## See also

- [Availability](availability.md): steady-state, until-probabilities, and MDP recovery cost in the
  same layer.
- [API reference](../api.md): `reach_probability`, `assert_probability`.
