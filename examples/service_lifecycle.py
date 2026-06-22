"""The zero-drift bridge: build a model straight from an allowed-transitions table.

Point musil at the very ``ALLOWED[entity]`` map your code already enforces and the model *is* the
code's table, so it can never drift -- there is no separate spec file to keep in sync. Here a small
service lifecycle stands in for that table. musil checks that every declared state is reachable with
no deadlock (sinks are declared terminal).

Run: python examples/service_lifecycle.py
"""

from __future__ import annotations

from dataclasses import dataclass

from musil import Model, check, declared_states, status_field_actions, terminal_states, to_dot

# a service lifecycle state machine, expressed as an allowed-transitions table
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
