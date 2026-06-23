# API reference

Everything below is re-exported from the top-level `musil` package, e.g. `from musil import Model, check`.

## Core — `check`, `Model`, `Action`

The model definition and the safety/deadlock/reachability checker.

::: musil.core

## Liveness — `check_liveness`

Eventually (`<>P`) and always-eventually (`[]<>P`) under weak and strong fairness.

::: musil.liveness

## Composition — `compose`

The interleaved product of independent component models.

::: musil.compose

## Channels — `channel_actions`, `send`

Model a message channel (reliable / lossy / duplicating; unordered, so reordering is free).

::: musil.channels

## FSM bridge — `transition_actions`, `status_field_actions`

Build a model straight from an allowed-transitions table, so it can't drift from the code.

::: musil.fsm

## Conformance — `generate_traces`, `replay`

Generate traces from the model and replay them against the real implementation.

::: musil.conformance

## Refinement — `check_refinement`, `RefinementMonitor`

Check that an observed run of the real system refines the model (each transition is a model edge or a
stutter) -- the oracle `simulate` uses to hold real code to a model-checked spec.

::: musil.refine

## Simulation — `simulate`, `Simulator`, `NetworkModel`, `FaultSchedule`

Deterministic simulation testing: run real event-driven node code under a controlled clock and a
fault-injecting network, reproducible from a seed, with invariants + refinement + a convergence goal
as the oracle. Beyond `NetworkModel`'s independent per-message loss, a `FaultSchedule` of **sustained,
heal-able** faults — network `Partition`s and node `Crash`es (with optional cold restart) — drives
VOPR-style **liveness** testing: after the faults heal, the system must converge to its goal (a
failure to do so is reported as `kind="liveness"`).

::: musil.sim

## Graph export — `to_dot`, `explore`

The reachable state graph and its Graphviz DOT rendering.

::: musil.graph
