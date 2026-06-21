"""The zero-drift bridge: build a model straight from an allowed-transitions table.

This is how musil is used in paas — point it at the real ``ALLOWED[entity]`` map and the model is
the code's table, so it can't drift. Here we use a small standalone copy of a service lifecycle.
musil checks every declared state is reachable with no deadlock (sinks declared terminal).

Run: python examples/paas_service.py
"""

from __future__ import annotations

from dataclasses import dataclass

from musil import Model, check, declared_states, status_field_actions, terminal_states, to_dot

# a service lifecycle (shape of paas state.py:ALLOWED["service"], standalone here)
ALLOWED: dict[str, set[str]] = {
    "pending": {"placed", "failed"},
    "placed": {"running", "failed", "stopped", "pending"},
    "running": {"stopped", "failed", "pending"},
    "failed": {"placed", "pending"},
    "stopped": {"placed"},
}


@dataclass(frozen=True)
class Service:
    status: str = "pending"


MODEL = Model(
    init=Service("pending"),
    actions=status_field_actions(ALLOWED),
    invariants={"status-declared": lambda s: s.status in declared_states(ALLOWED)},
    terminal=lambda s: s.status in terminal_states(ALLOWED),
)


if __name__ == "__main__":
    result = check(MODEL)
    print(result)
    print(f"reached {result.states_explored} of {len(declared_states(ALLOWED))} declared states")
    print("\n--- DOT ---")
    print(to_dot(MODEL))
