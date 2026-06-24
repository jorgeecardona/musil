# Traffic light — the minimal musil model

**What this teaches:** how to express a finite-state machine as states + guarded actions, prove a safety invariant, and export the reachable graph as Graphviz DOT.

## The system

A traffic light cycles through three colours: `red → green → yellow → red`.
There is exactly one state field (`color`) and one action per edge in the cycle.
The safety invariant says the colour is always one of the three known values — nothing stranger can happen.

This is the smallest model that exercises every core concept at once:

- a frozen dataclass as the state type
- three `Action` objects as the transitions
- an invariant checked in every reachable state
- `to_dot` for a visual sanity check

## What musil finds

The BFS explores three states (`red`, `green`, `yellow`) and confirms the invariant holds in all of them.
No counterexample, no deadlock.

```
Result(ok=True, states=3)
```

`to_dot` emits Graphviz DOT that you can pipe to `dot -Tsvg` to get a picture of the three-node cycle.

## Source

```python
--8<-- "examples/traffic_light.py"
```

## Run it

```
python examples/traffic_light.py
```

## See also

- [Service lifecycle](service_lifecycle.md) — builds a model directly from a transition table using `status_field_actions`, so the spec and the code share a single source of truth.
- [Lost update](lost_update.md) — the next step: two actors sharing state, where the bug lives in the interleaving.
