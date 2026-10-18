# musil

A tiny, dependency-free explicit-state model checker for Python: safety, deadlock, reachability,
liveness — and concurrency by interleaving.

You describe a system as *states*, the guarded *actions* that step between them, and *invariants*
that must hold in every state. musil explores every reachable state, in every order concurrent
actions can run, and either returns the shortest sequence of steps that breaks a rule or confirms
none can. Your states are frozen dataclasses, your invariants are predicates, and the whole thing
runs in pytest next to your other tests — no spec language, no external binary, no JVM.

("Explicit-state" means it enumerates reachable states one by one rather than reasoning about them
symbolically — simple, and exact for systems small enough to fit.)

Named for Robert Musil, the engineer-mathematician turned novelist.

## Install

```
pip install musil      # or: uv add musil
```

Pure standard library; Python 3.12+.

## Quickstart

A lost-update race: two actors each increment a shared counter as two non-atomic steps (read, then
write back `read + 1`). A normal test hits the bug only on an unlucky interleaving. musil checks
*every* interleaving and returns the shortest one that loses an update.

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

```
INVARIANT VIOLATED: both-increments-counted
  Init: Counter(x=0, a_reg=None, b_reg=None, a_done=False, b_done=False)
  → A_read: Counter(x=0, a_reg=0, b_reg=None, a_done=False, b_done=False)
  → B_read: Counter(x=0, a_reg=0, b_reg=0, a_done=False, b_done=False)
  → A_write: Counter(x=1, a_reg=None, b_reg=0, a_done=True, b_done=False)
  → B_write: Counter(x=1, a_reg=None, b_reg=None, a_done=True, b_done=True)
(12 states explored)
```

In a test, `check(model)` is truthy exactly when it holds, so `assert check(model).ok` passes or
fails with that trace. The result also carries the broken invariant, the `trace`, and
`states_explored`. This is [`examples/lost_update.py`](examples/lost_update.py); the Peterson mutual-exclusion
proof is in [`examples/mutex.py`](examples/mutex.py), and ~30 more runnable models live in
[`examples/`](examples/).

## Why musil

The expensive bugs in stateful and distributed systems are temporal and concurrent: a resource
wedged forever, a race that drops data, a deadlock. Tests sample executions; a model checker proves
a property over *all* of them.

TLA+/TLC is the reference tool in this space, and it scales further than musil. But its model is a
separate `.tla` spec in a math-based language, checked by a JVM binary, living outside your code and
test suite. musil's bet is the opposite: the model is ordinary Python *in* your repo. States are
frozen dataclasses, actions are guarded functions, invariants are predicates, and `check` runs under
pytest like any other test. The model can even be driven from the same allowed-transitions table
your code already enforces (`musil.fsm`), so it can't silently drift from the code.

**Reach for musil when** your state space is bounded and small, you want the model next to the code
with zero new tooling, and the win is catching races / deadlocks / stuck states and proving
convergence.

**Reach for TLA+ (or a symbolic tool like Apalache) when** the state space is large or infinite and
you need symbolic reasoning rather than enumeration — musil enumerates, so it is for bounded models
and blows up on very large ones (cap it with `max_states`; the result flags `truncated`).
`check_inductive` pushes the *depth* bound to unbounded via k-induction, but still enumerates a
bounded domain of candidate states.

## Key features

- **Safety** — `check(model)` sweeps every reachable state and returns the shortest trace to a broken
  invariant or a deadlock, or confirms none exists. `reachable_violations` lists every offending
  state/rule for a full audit.
- **Concurrency by interleaving** — hand it each actor's actions and it tries every order they can
  run in, surfacing races a normal test would only hit by luck.
- **Deadlock & reachability** — a state with no next step is reported as a bug unless declared
  `terminal`; `reaches(graph, P)` answers "from which states can P still be reached?".
- **Liveness** — `check_liveness(model, goal=P)` proves something good eventually (or always
  eventually) happens, with weak/strong **fairness** assumptions; failures come back as a lasso
  (stem into a repeating cycle).
- **Dependency-free & typed** — standard library only, ships `py.typed`, pyright-strict.

Beyond these, musil also does full LTL (`check_ltl`), exact DTMC/MDP probabilities
(`musil.probabilistic`), k-induction (`check_inductive`), coverage & vacuity analysis, and
model-building kits (`compose`, channels, `musil.fsm`, open-system checking, `simulate`). Every
claim has a runnable model in [`examples/`](examples/); the full feature tour lives in the
[`docs/`](docs/).

## Links

- **Repository:** https://gitlab.com/cardona-oss/musil
- **PyPI:** https://pypi.org/project/musil/
- **Changelog:** [CHANGELOG.md](CHANGELOG.md)
- **Documentation:** <https://cardona-oss.gitlab.io/musil/>

## Contributing

Toolchain, CI, and the release process live in [CONTRIBUTING.md](CONTRIBUTING.md). In short:
`proto install` then `moon run :ci` (lint + typecheck + test + build + docs); releases publish
themselves from a green `main` pipeline.

## License

MIT © Jorge Cardona. See [LICENSE](LICENSE).
