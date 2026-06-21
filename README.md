# musil

A tiny, dependency-free **explicit-state model checker** for Python. Describe a system as states +
guarded transitions + invariants; musil exhaustively sweeps every reachable state — and every
interleaving of concurrent actors — and hands you the shortest counterexample when something breaks.

Named for Robert Musil, the engineer-mathematician turned novelist.

```python
from dataclasses import dataclass, replace
from musil import Action, Model, check

@dataclass(frozen=True)
class Light:
    color: str = "red"

model = Model(
    init=Light("red"),
    actions=[
        Action("go",   lambda s: s.color == "red",    lambda s: replace(s, color="green")),
        Action("slow", lambda s: s.color == "green",  lambda s: replace(s, color="yellow")),
        Action("stop", lambda s: s.color == "yellow", lambda s: replace(s, color="red")),
    ],
    invariants={"known-color": lambda s: s.color in {"red", "green", "yellow"}},
)

print(check(model))   # OK -- 3 states, no violations
```

## Why

The expensive bugs in stateful and distributed systems are **temporal and concurrent**: a resource
wedged forever, a race that drops data, a deadlock. Tests sample executions; a model checker proves
properties over *all* of them. musil exists to do that **in Python, as a library** — no separate
spec language, no external binary, no JVM. Your states are frozen dataclasses, your invariants are
predicates, and the whole thing runs in pytest next to your other tests.

The key move: **the model can be driven from the same data your code uses.** Point
`transition_actions` at your real allowed-transitions table and the model can't drift from the code —
it *is* the code's table.

## Install

```
pip install musil      # or: uv add musil
```

Pure standard library; Python 3.12+.

## What it checks

**Safety + deadlock + reachability** — `check(model) -> Result`:

```python
result = check(model)
result.ok                 # True if every reachable state satisfied every invariant, no deadlock
print(result)             # on failure: the broken invariant (or "deadlock") + shortest trace
```

A state with no enabled action is a **deadlock** unless you mark it terminal
(`Model(..., terminal=lambda s: ...)`) — an absorbing sink like `deleted`.

**Concurrency, for free** — model each actor's steps as actions and hand musil all of them; it fires
every enabled action from every state, so all interleavings are explored:

```python
# two non-atomic increments race; musil finds the lost update
check(Model(init=Counter(), actions=[*actor_a, *actor_b], invariants={...}))
```

**Liveness** — `check_liveness(model, goal=P) -> LivenessResult`:

```python
# "eventually P" on every run; everywhere=True checks "always eventually P" (recurrence/convergence)
check_liveness(model, goal=lambda s: s.served == s.desired, everywhere=True, fair=["reconcile"])
```

A liveness failure is reported as a **lasso**: a stem into a recurring set plus the cycle. Pass
`fair=[...]` to assume **weak fairness** of those actions (an action continuously enabled along a
cycle must eventually be taken), or `fair_strong=[...]` for **strong fairness** (enabled *infinitely
often* ⇒ eventually taken — what you need for delivery over a lossy channel). Pick the weakest that
makes the property hold; over-strong fairness hides real bugs.

**Compose & model the network** — `compose(...)` builds the interleaved product of independent
component models, lifting each component's invariants (name-qualified) and letting you add joint
invariants over the whole; the channel kit (`channel_actions`, `send`) models a message channel —
reliable / lossy / duplicating, and unordered so **reordering is explored for free** — so you can
specify each component once and check the assembled system.

**Zero-drift from a transition table** — `transition_actions` / `status_field_actions`:

```python
from musil import status_field_actions, terminal_states
model = Model(
    init=Service("pending"),
    actions=status_field_actions(ALLOWED["service"]),     # generated from YOUR table
    terminal=lambda s: s.status in terminal_states(ALLOWED["service"]),
)
```

**Visualize** — `to_dot(model)` returns Graphviz DOT (`dot -Tsvg`); pass `highlight=[s.state for s in
result.trace]` to colour a counterexample.

## How it compares

| | what it is | spec language | runs the real code? | liveness |
|---|---|---|---|---|
| **musil** | in-Python library, explicit-state | Python (frozen dataclasses) | the model can be driven from your code's tables | safety + weak/strong-fairness liveness |
| TLA+ / TLC | standalone checker | TLA+ (math) | no (separate model) | full temporal logic |
| P | DSL + systematic testing, compiles to C | P (state machines) | yes (executable model) | safety + liveness |
| Stateright | Rust library, model-check + run | Rust | yes (same actors on a real network) | safety + liveness |
| FizzBee | Go binary, Python-like DSL | `.fizz` | no | safety + basic liveness |

musil is the **smallest** member of this family: pick it when your state space is bounded and small,
you want the model *in* your test suite with zero new tooling, and the win is catching races /
deadlocks / stuck states and proving convergence.

## Honest limitations

- **Explicit-state**: it enumerates reachable states, so it's for **bounded** models. Big or infinite
  state spaces blow up (use a `max_states` cap; the result reports `truncated`). Symbolic/SMT tools
  (TLA+'s Apalache, etc.) scale further.
- **No partial-order reduction (yet)**: heavy concurrency interleaving can be expensive.
- **Liveness is fairness-based, not full LTL**: `<>P` and `[]<>P` under weak *and* strong fairness,
  not arbitrary temporal-logic formulae.
- It checks the **model**. Whether your implementation refines the model is a separate question —
  `generate_traces` + `replay` give you conformance testing (generate from the model, replay against
  the code) as a pragmatic bridge.

## Provenance

musil grew out of keeping a real control plane (a Railway/Heroku-style PaaS) correct. It is exercised
there against the actual state machines and concurrency: the allowed-transition tables, a concurrent
cert-vs-service-death race that reproduces a real outage, the ingress route-delivery convergence
proof, a multi-replica hub fan-out (showing leader election alone doesn't fix delivery across
replicas), and the overlay full-mesh. The core has **zero** dependencies on that project — it is a
standalone library.

## Releasing

CI publishes to PyPI on a git tag via **OIDC Trusted Publishing** — no API token is stored anywhere.
One-time setup on PyPI (Account → Publishing → add a *pending* GitLab publisher; or add it to the
project after the first manual upload):

| Field | Value |
|-------|-------|
| PyPI Project Name | `musil` |
| Namespace | `jorgeecardona` |
| Project name (repo) | `musil` |
| Top-level pipeline file | `.gitlab-ci.yml` |
| Environment name | `pypi` |

Then cut a release:

```
# bump version in pyproject.toml + add a CHANGELOG entry, commit, then:
git tag v0.1.0 && git push origin v0.1.0
```

The tag pipeline builds the sdist+wheel and the `publish` job exchanges GitLab's OIDC token for a
short-lived PyPI token and uploads. Pushes and MRs run lint + typecheck + tests only.

## License

MIT © Jorge Cardona. See [LICENSE](LICENSE).
