<h1 align="center">musil</h1>

<p align="center"><strong>Find races and deadlocks in a pytest test: musil checks every order your concurrent actions can run in and returns the shortest failing trace.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/musil/"><img alt="PyPI" src="https://img.shields.io/pypi/v/musil?style=flat-square"></a>
  <a href="https://pypi.org/project/musil/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/musil?style=flat-square"></a>
  <a href="https://musil-d34e71.gitlab.io/"><img alt="Docs" src="https://img.shields.io/badge/docs-musil--d34e71.gitlab.io-blue?style=flat-square"></a>
  <a href="https://gitlab.com/cardona-oss/musil/-/pipelines"><img alt="Pipeline" src="https://img.shields.io/gitlab/pipeline-status/cardona-oss%2Fmusil?branch=main&style=flat-square"></a>
  <a href="https://gitlab.com/cardona-oss/musil/-/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://musil-d34e71.gitlab.io/textbook/">Examples</a> ·
  <a href="https://musil-d34e71.gitlab.io/verifying-distributed-systems/">Verifying a distributed system</a> ·
  <a href="https://musil-d34e71.gitlab.io/#why-musil">Why musil</a> ·
  <a href="https://musil-d34e71.gitlab.io/api/">API reference</a> ·
  <a href="https://gitlab.com/cardona-oss/musil/-/blob/main/CHANGELOG.md">Changelog</a>
</p>

---

## Overview

musil is a model checker with no dependencies. You write states as frozen dataclasses, actions as
guarded functions and invariants as predicates. `check` runs in a pytest test. It explores every
reachable state, in every order the concurrent actions can run, and returns the shortest trace
that breaks an invariant, or confirms that none exists.

It enumerates states one by one, so it is for bounded models. TLA+ scales further, but needs a
separate spec language and a JVM.

It also checks deadlock, liveness under fairness, LTL (linear temporal logic) formulas, and exact
probabilities on Markov chains and Markov decision processes.

Status: beta.

## Install

```bash
pip install musil      # or: uv add musil
```

Standard library only. Python 3.12+.

## Quickstart

A lost-update race: two actors each increment a shared counter in two steps (read, then write
back `read + 1`). A normal test fails only on one unlucky interleaving. musil checks every
interleaving and returns the shortest one that loses an update.

```python
from dataclasses import dataclass, replace
from musil import Action, Model, check


@dataclass(frozen=True)
class Counter:
    x: int = 0
    a_reg: int | None = None   # A's read-but-not-yet-written value
    b_reg: int | None = None
    a_done: bool = False
    b_done: bool = False


model = Model(
    init=Counter(),
    actions=[
        Action("A_read", lambda s: s.a_reg is None and not s.a_done, lambda s: replace(s, a_reg=s.x)),
        Action(
            "A_write",
            lambda s: s.a_reg is not None,
            lambda s: replace(s, x=(s.a_reg or 0) + 1, a_reg=None, a_done=True),
        ),
        Action("B_read", lambda s: s.b_reg is None and not s.b_done, lambda s: replace(s, b_reg=s.x)),
        Action(
            "B_write",
            lambda s: s.b_reg is not None,
            lambda s: replace(s, x=(s.b_reg or 0) + 1, b_reg=None, b_done=True),
        ),
    ],
    invariants={"both-increments-counted": lambda s: not (s.a_done and s.b_done) or s.x == 2},
    terminal=lambda s: s.a_done and s.b_done,
)

print(check(model))
```

```text
INVARIANT VIOLATED: both-increments-counted
  Init: Counter(x=0, a_reg=None, b_reg=None, a_done=False, b_done=False)
  → A_read: Counter(x=0, a_reg=0, b_reg=None, a_done=False, b_done=False)
  → B_read: Counter(x=0, a_reg=0, b_reg=0, a_done=False, b_done=False)
  → A_write: Counter(x=1, a_reg=None, b_reg=0, a_done=True, b_done=False)
  → B_write: Counter(x=1, a_reg=None, b_reg=None, a_done=True, b_done=True)
(12 states explored)
```

In a test, write `assert check(model).ok`. The result is truthy only when every invariant holds and
no state deadlocks. It also has the broken invariant, the `trace`, and `states_explored`.

This model is
[`examples/lost_update.py`](https://gitlab.com/cardona-oss/musil/-/blob/main/examples/lost_update.py).
The Peterson mutual-exclusion proof is in
[`examples/mutex.py`](https://gitlab.com/cardona-oss/musil/-/blob/main/examples/mutex.py). About 30
more runnable models are in
[`examples/`](https://gitlab.com/cardona-oss/musil/-/tree/main/examples).

## Why musil

The expensive bugs in stateful and distributed systems are temporal and concurrent: a resource
that stays stuck, a race that drops data, a deadlock. Tests sample executions. A model checker
proves a property over all of them.

TLA+ with its checker TLC is the reference tool, and it scales further than musil. Its model is a
separate `.tla` spec in a math-based language, checked by a JVM program, outside your code and
your test suite.

A musil model is ordinary Python in your repo. States are frozen dataclasses, actions are guarded
functions, invariants are predicates, and `check` runs under pytest like any other test. You can
build the model from the same allowed-transitions table your code enforces (`musil.fsm`). Then a
change to the table changes the model too.

Use musil when the state space is bounded and small, you want the model next to the code with no
new tooling, and you want to catch races, deadlocks and stuck states, or prove convergence.

Use TLA+ (or a symbolic tool like Apalache) when the state space is large or infinite and you
need symbolic reasoning. musil enumerates states, so a very large model runs out of time or
memory. Cap it with `max_states`: the result then sets `truncated`.

`musil.induction.check_inductive` removes the depth bound with k-induction. It still enumerates a
bounded domain of candidate states.

## Key features

- Safety: `check(model)` visits every reachable state and returns the shortest trace to a broken
  invariant or a deadlock, or confirms none exists. `musil.core.reachable_violations` lists every
  offending state and rule.
- Concurrency by interleaving: give it each actor's actions and it tries every order they can
  run in. It finds races that a normal test hits only by luck.
- Deadlock and reachability: a state with no next step is reported as a bug unless declared
  `terminal`. `reaches(graph, P)` answers "from which states can P still be reached?".
- Liveness: `check_liveness(model, goal=P)` proves that P eventually happens (or happens again
  and again), under weak or strong fairness assumptions. A failure is a lasso: a stem that leads
  into a repeating cycle.
- No dependencies, and typed: standard library only, ships `py.typed`, passes pyright strict.

musil also has LTL (`check_ltl`), exact probabilities on Markov chains and Markov decision
processes (`musil.probabilistic`), k-induction (`musil.induction.check_inductive`), coverage and
vacuity analysis (`musil.metrics`), and kits to build models (`musil.compose`, `musil.channels`,
`musil.fsm`, open-system checking in `musil.env`, `musil.sim.simulate`).

Each feature has a runnable model in
[`examples/`](https://gitlab.com/cardona-oss/musil/-/tree/main/examples). The feature tour is in
the [docs](https://musil-d34e71.gitlab.io/).

## Links

- Documentation: <https://musil-d34e71.gitlab.io/>
- Repository: <https://gitlab.com/cardona-oss/musil>
- PyPI: <https://pypi.org/project/musil/>
- Changelog: [CHANGELOG.md](https://gitlab.com/cardona-oss/musil/-/blob/main/CHANGELOG.md)

## Contributing

Toolchain, CI and the release process are in
[CONTRIBUTING.md](https://gitlab.com/cardona-oss/musil/-/blob/main/CONTRIBUTING.md). Run
`proto install`, then `moon run :ci` (lint, typecheck, test, build, docs). A green `main`
pipeline publishes a release when the version is new.

## License

musil is named for Robert Musil, the engineer-mathematician turned novelist.

MIT © Jorge Cardona. See [LICENSE](https://gitlab.com/cardona-oss/musil/-/blob/main/LICENSE).
