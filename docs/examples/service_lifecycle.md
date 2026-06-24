# Service lifecycle — zero-drift spec from a transition table

**What this teaches:** how to build a model directly from the allowed-transitions table your code already enforces, so the spec and the implementation share a single source of truth and can never diverge.

## The problem: drift between spec and code

The standard way to write a model checker spec is to hand-code the guards and transitions separately from the production state machine. Those two artefacts then drift — a new transition is added to the code, the spec is forgotten, and the checker proves a property of a system that no longer exists.

The solution is to feed `status_field_actions` the exact `ALLOWED` dict your code uses at runtime:

```python
ALLOWED: dict[str, set[str]] = {
    "pending": {"placed", "failed"},
    "placed":  {"running", "failed", "stopped", "pending"},
    "running": {"stopped", "failed", "pending"},
    "failed":  {"placed", "pending"},
    "stopped": {"placed"},
}
```

musil reads that map and generates one `Action` per legal edge. There is no separate spec file — the model *is* the table.

## What musil checks

- **Safety:** every reachable `status` value is one of the declared states. No transition leads somewhere uncharted.
- **Deadlock:** every state with no declared successors is marked terminal; no state is a surprise dead end.
- **Full reachability:** the BFS visits all declared states, confirming the table has no unreachable corners.

```
reached 5 of 5 declared states
Result(ok=True, states=5)
```

`terminal_states(ALLOWED)` derives the sinks (`stopped`), and `declared_states(ALLOWED)` gives the full set — both computed from the same dict, never written twice.

## Source

```python
--8<-- "examples/service_lifecycle.py"
```

## Run it

```
python examples/service_lifecycle.py
```

## See also

- [Traffic light](traffic_light.md) — the minimal FSM with hand-coded transitions.
- [Lost update](lost_update.md) — what happens when two actors share state and their steps interleave.
