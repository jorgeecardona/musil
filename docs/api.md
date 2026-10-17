# API reference

The **core checking API** is exported from the top-level `musil` package — modelling (`Model`, `Action`),
the checks (`check`, `check_all`, `explore`, `check_liveness`, `check_ltl`), results and traces (`Result`,
`Step`, `format_trace`, `witness`, …), the LTL formula AST, and the test assertions (`assert_ok`,
`assert_violates`). Everything else lives in a **submodule**, imported directly — e.g.
`from musil.probabilistic import reach_probability`, `from musil.env import check_open`,
`from musil.metrics import coverage`. This reference is grouped the same way: the core first, then each layer
under the concern it serves. See [migrating](migrating.md) for the import-path changes from the pre-0.35 flat
namespace.

## Core

The model, the safety/deadlock/reachability checker, traces, and the test assertions — the top-level API.

::: musil.core

## Temporal logic

Liveness and full linear-temporal-logic checking, plus the named pattern sugar.

::: musil.ltl

::: musil.liveness

::: musil.patterns

## Probabilistic & simulation

Exact DTMC/MDP verification (rational arithmetic, no floating point), and the sampling-based simulator for
faulty distributed runs.

::: musil.probabilistic

::: musil.sim

## Systems & modelling

Open-system checking against adversarial environments, composition, and the model-building kits.

::: musil.env

::: musil.compose

::: musil.channels

::: musil.faults

::: musil.fsm

::: musil.petri

::: musil.clock

::: musil.reconciler

## Reductions & proof

State-space reductions with their soundness gates, and proof by induction beyond the explored scope.

::: musil.por

::: musil.symmetry

::: musil.induction

## Conformance to code

Checking that real code behaves like the model — trace replay and refinement.

::: musil.conformance

::: musil.refine

## Analysis, tracing & tooling

Coverage and vacuity, counterexample tools, model diffing, caching, profiling, and the adoption helpers.

::: musil.metrics

::: musil.counterexample

::: musil.diffing

::: musil.cache

::: musil.profiling

::: musil.doctor

::: musil.citations

::: musil.graph

::: musil.history

::: musil.tracing
