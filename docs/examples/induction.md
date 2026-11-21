# Induction: proving beyond the explored scope

**What this teaches:** `check` is exhaustive only up to the states it sweeps (and up to
`max_states`). `check_inductive` proves an invariant a different way (by *k-induction* over the
transition relation) so a pass holds at **unbounded depth**: every reachable state, at any scope.
The price is a finite `domain` of candidate states to quantify over, which must include
*unreachable* ones (1-induction over only the reachable set proves nothing `check` didn't already).
The interesting case is an invariant that is **true on every reachable state yet not inductive**,
and the *counterexample-to-induction* that tells you how to fix it.

## The model

A counter steps by two, so the reachable values are `{0, 2, 4, 6, 8}`:

```python
COUNTER = Model(
    init=Counter(0),
    actions=[Action("step", enabled=lambda s: s.x < 8, apply=lambda s: Counter(s.x + 2))],
    terminal=lambda s: s.x == 8,
)
DOMAIN = [Counter(x) for x in range(10)]  # 0..9 — INCLUDES the unreachable odd states
```

The bound `x <= 8` holds on all five reachable states, so `check` is green.

## A green check that isn't inductive

=== "The CTI"

    ```python
    check_inductive(COUNTER, lambda s: s.x <= 8, DOMAIN)
    # proven = False
    # counterexample-to-induction: Counter(x=7) --step--> Counter(x=9)
    ```

    `x <= 8` is not inductive: from the **unreachable** odd pre-state `x = 7` (which still satisfies
    `x <= 8`) one step reaches `x = 9`, breaking it. `check_inductive` hands back exactly that
    pre-state and successor. The pre-state is unreachable, so `check` never sees it; induction
    quantifies over the whole `domain`, so it does.

=== "The fix: strengthen"

    ```python
    check_inductive(COUNTER, lambda s: s.x <= 8 and s.x % 2 == 0, DOMAIN)
    # proven = True
    ```

    The fix is to **strengthen** the invariant so the bad pre-state no longer satisfies the
    antecedent. Add that `x` is even. Now the odd pre-states are excluded, every even `x <= 8` steps
    to an even `x <= 8`, and the invariant holds at unbounded depth. You strengthen the invariant,
    you do *not* widen the scope.

??? note "Why the domain must include unreachable states"

    1-induction over only the *reachable* set is trivially true for any model that already passes
    `check` (a reachable state's successors are reachable, hence satisfy the invariant) so it proves
    nothing new. The unreachable odd states are exactly what makes the step obligation bite, and
    exactly where the CTI lives. This is the IC3/PDR workflow in miniature: a green `check` up to a
    bound, an inductive proof for all depths, and a CTI that says how to strengthen.
    `check_inductive` still *enumerates* the domain, so an infinite value space (unbounded integers,
    unbounded components) needs a symbolic solver. See `src/musil/INDUCTION_NOTES.md`.

## Source

```python
--8<-- "examples/induction.py"
```

## Run it

```
python examples/induction.py
```

## See also

- [API reference](../api.md): `check_inductive`, `InductionResult`.
- The README "What it checks" section. Induction beside safety, liveness, LTL, and the probabilistic
  layer.
