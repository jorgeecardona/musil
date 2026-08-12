---
title: A green check cannot say whether an action was ever enabled or an invariant ever exercised
status: in-progress
area: metrics
owner: sleek-ultron-08f00
filed: 2026-08-12
scope: S
verify: test
---

Source: gitlab.com/jorgeecardona/musil issue #2 (item 1 of four), filed 2026-08-12. Ranked first there and here: it is the only one of the four that is pure post-hoc analysis over a graph musil already builds.

## MEASURED (in this repo)

- `metrics_of` reports size and branching only — `reachable_states`, `transitions`, `initial_states`, `terminal_states`, `max_branching`, `mean_branching`, `truncated` ([src/musil/metrics.py:26-66](../../src/musil/metrics.py#L26-L66)). `solution_cardinality` counts states matching a predicate ([src/musil/metrics.py:77](../../src/musil/metrics.py#L77)). Nothing reports on *actions* or on whether an invariant did any work.
- `check` returns `Result(ok=True, states_explored=N)` and its `__str__` is `OK — N states, no violations` ([src/musil/core.py:126-128](../../src/musil/core.py#L126-L128)). Neither carries a coverage view.
- `explore` already evaluates `action.enabled(state)` for every action at every reachable state ([src/musil/core.py:284-288](../../src/musil/core.py#L284-L288)), and `reachable_violations` already evaluates every invariant at every reachable state ([src/musil/core.py:446-455](../../src/musil/core.py#L446-L455)). Both facts needed here are computed and discarded.
- `grep -rniE "coverage|vacuous|vacuity|dead.action" src/` returns 0 hits.

## The finding

Three ways a green result can mean nothing, none of them currently visible:

1. **A dead action** — `enabled` is false in every reachable state. Usually a guard bug, and it silently removes behaviour the author believed was being explored. The interleaving never happened; the run still says OK.
2. **A vacuous invariant** — it holds because its antecedent is never reached. `not s.replied or s.now <= deadline` passes trivially in a model where nothing ever replies.
3. **An always-enabled action**, which is the weaker smell of the same family: a guard that never guards.

The first is the sharpest, because it is unambiguous: an action that can never fire is either dead code or a bug, never a design choice worth keeping silent.

## CORRECTION, found while implementing (2026-08-12)

The invariant half of this issue as first written does not work, and the version above is kept so the
mistake is on the record. It proposed reporting invariants that "returned the same verdict across
the whole reachable space" as vacuous. **In a model that passes, every invariant is constantly
true** — that is what passing means. So the signal fires on every healthy model, and a report that
is always on is not a report.

Real vacuity detection needs the invariant's *antecedent*, and musil invariants are opaque
`Callable[[S], bool | str | None]`. Nothing observable from outside distinguishes "holds because the
design is correct" from "holds because its premise is never reached". Detecting that would need the
user to supply the antecedent as a separate predicate, which is a different feature with a different
API, and is not filed here.

Action coverage survives unchanged: it needs no internals and does not fire on healthy models.

## Done

A `coverage(model)` / `coverage_of(graph, model)` pair in `metrics.py` reporting, over the reachable
graph: action names never enabled anywhere (dead), enabled everywhere (the guard never guards), and
enabled but only ever self-looping (the action never changes anything). Observation that will be
true: a model with a deliberately-unsatisfiable guard names that action as dead, a model whose
action is always enabled names it, a healthy model names none, and each is the *set of names* rather
than an accusation. `Result` gains no new field — this is a separate call, so `check` keeps its one
job.

Truncation must propagate: under `truncated=True` a "dead" action is only *not-yet-seen-enabled*, which is a different claim, and the report has to say so rather than accuse.

`verify: test` — every assertion is a set of names computed in-process.

## Deliberately NOT doing

- **Not folding it into `check`.** A coverage pass costs a second sweep of actions over the graph, and `check` early-exits at the first violation by design ([src/musil/core.py:155-157](../../src/musil/core.py#L155-L157)) — a partial graph gives a wrong coverage answer. Separate call, complete graph.
- **Not reporting "unreached invariant branches"** or anything requiring the invariant's internal structure. musil invariants are opaque callables; the honest observable is the verdict, not the reason it was reached.
- **No coverage percentage.** metrics.py already refuses to fabricate a single "determinism score" ([src/musil/metrics.py:15](../../src/musil/metrics.py#L15)); a coverage percentage would be the same mistake — the names are the finding.