# Changelog

All notable changes to musil are documented here. Versioning is [SemVer](https://semver.org/).

## [0.1.0] - 2026-06-21

Initial release.

### Added
- **Core checker** (`check`) — breadth-first sweep of every reachable state for the first invariant
  violation or deadlock, with the shortest counterexample trace. States are immutable, hashable
  values (frozen dataclasses); actions are pure guarded transitions.
- **Concurrency by interleaving** — modelling several actors is just handing `check` all their
  actions; every interleaving is explored.
- **Liveness** (`check_liveness`) — proves `<>P` ("eventually P") and, with `everywhere=True`,
  `[]<>P` ("always eventually P" / convergence). Tarjan SCC + lasso counterexamples. **Weak** fairness
  via `fair=[...]` and **strong** fairness via `fair_strong=[...]`.
- **Composition** (`compose`) — the interleaved product of independent component models, lifting each
  component's invariants (name-qualified) and supporting joint invariants over the composite.
- **Channel kit** (`channel_actions`, `send`) — model a message channel as a building block:
  reliable / lossy / duplicating, unordered so reordering is explored for free.
- **Zero-drift FSM bridge** (`transition_actions`, `status_field_actions`, `terminal_states`,
  `declared_states`) — build a model straight from an allowed-transitions table so it can't diverge
  from the code.
- **Conformance** (`generate_traces`, `replay`) — generate traces from the model and replay them
  against the real implementation to check it refines the model.
- **Graph export** (`to_dot`) — Graphviz DOT of the reachable state graph, with counterexample
  highlighting; plus `explore` for the raw reachable graph.
- **CLI** (`python -m musil <model.py>`) — check a model module from the command line.
- PEP 695 generics, `py.typed`, zero runtime dependencies, Python 3.12+.

### Known limitations
- Explicit-state: for bounded models (use the `max_states` cap; results flag `truncated`).
- No partial-order reduction yet; heavy interleaving can be expensive.
- Liveness is fairness-based, not full LTL (`<>P` / `[]<>P` under weak/strong fairness).
