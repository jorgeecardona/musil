# River crossing: solving a puzzle by reachability

**What this teaches:** a model checker is also a *planner*. Make the illegal moves impossible, ask
whether the goal is reachable, and the witness path *is* the plan. No probabilities, no temporal
logic. Just reachability over a tiny finite graph, with an exact answer.

A farmer must ferry a wolf, a goat, and a cabbage across a river. The boat holds the farmer and at
most one item. Left unwatched together, the wolf eats the goat, or the goat eats the cabbage. Get
everything across with nothing eaten.

## The model

The state is which bank each of the four is on. Each crossing is guarded so it may fire only when
the item is on the farmer's bank **and the resulting position is safe**. So illegal states are never
entered, and every reachable state is a legal position:

```python
def _safe(s: Bank) -> bool:  # (1)!
    goat_unwatched = s.farmer != s.goat
    return not (goat_unwatched and (s.wolf == s.goat or s.goat == s.cabbage))

def _move(name: str, carry: str | None) -> Action[Bank]:  # (2)!
    return Action(name,
                  enabled=lambda s: _present(s, carry) and _safe(_apply_move(s, carry)),
                  apply=lambda s: _apply_move(s, carry))
```

1.  Nothing gets eaten: the goat is never left with the wolf, or with the cabbage, while the farmer
    is on the other bank.
2.  A crossing exists only if it lands in a safe state. The illegal positions are not "checked and
    rejected". They are never generated, so any path the search finds is automatically a valid
    solution.

## Finding the plan

Ten states are reachable, and the goal is seven crossings away. Two equivalent framings:

=== "Ask for the path: `witness`"

    ```python
    graph = explore(RIVER)
    plan = witness(graph, everyone_across)   # the shortest path to a goal state
    print(format_trace(plan, render=_render))
    ```

    `witness` returns the shortest trace from the start to *some* state satisfying the predicate.
    Here, the seven-crossing solution. `reaches(graph, everyone_across)` answers the same
    reachability question as a yes/no; `witness` hands back the concrete steps.

=== "Refute 'no solution': `check`"

    ```python
    # Give the model the invariant "the goal is never reached" and check refutes it:
    result = check(replace(RIVER, invariants={"not-across": lambda s: s != GOAL}))
    print(format_trace(result.trace))       # the same seven crossings, as a counterexample
    ```

    Finding a plan and refuting the claim "no plan exists" are the *same computation*: the
    counterexample to "the goal is unreachable" is exactly the plan. This is the idiom for solving
    puzzles with a safety checker.

??? note "The seven-crossing solution"

    ```
    take goat  → farmer=R wolf=L goat=R cabbage=L
    row alone  → farmer=L wolf=L goat=R cabbage=L
    take wolf  → farmer=R wolf=R goat=R cabbage=L
    take goat  → farmer=L wolf=R goat=L cabbage=L
    take cabbage → farmer=R wolf=R goat=L cabbage=R
    row alone  → farmer=L wolf=R goat=L cabbage=R
    take goat  → farmer=R wolf=R goat=R cabbage=R
    ```

    The goat is the only item that cannot be left with either other, so it shuttles back and forth:
    over first, and brought *back* on the middle trip so the wolf and cabbage are never left with
    it.

## Source

```python
--8<-- "examples/river_crossing.py"
```

## Run it

```
python examples/river_crossing.py
```

## See also

- [API reference](../api.md): `witness`, `path_to`, `reaches`, `states_where`, `format_trace`.
- [Traffic light](traffic_light.md): the same reachable-graph search on a simple finite-state
  machine.
