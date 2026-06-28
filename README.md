# musil

A tiny, dependency-free **model checker** for Python. You describe a system as *states*, the *steps*
that move between them (each guarded by a condition saying when it can happen), and *invariants*
(rules that must hold in every state). musil then explores every state the system can reach — and
every order in which concurrent steps can happen — and hands you the shortest sequence of steps that
breaks a rule, or confirms none can. ("Explicit-state" means it enumerates those states one by one,
rather than reasoning about them symbolically — simple, and exact for systems small enough to fit.)

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

**Safety — "nothing bad ever happens"** — `check(model) -> Result`. Safety means a rule (invariant)
holds in *every* state the system can reach, e.g. "two clients never hold the lock at once." `check`
visits every reachable state, in every order the concurrent steps can run, and returns the shortest
sequence of steps that breaks a rule — or confirms none can.

```python
result = check(model)
result.ok                 # True if every reachable state satisfied every rule, with no deadlock
print(result)             # on failure: the broken rule (or "deadlock") + the shortest steps to it
```

A **deadlock** is a state with no possible next step — the system is stuck. musil reports it as a
bug *unless* you declare that state a legitimate resting point with `terminal=...` (e.g. a `deleted`
record, which nothing should ever leave).

An invariant returns `True` (holds) or `False` (broken). It may also return a **string**, meaning
"broken, and here's why" — that text appears in the counterexample, so you learn *which* rule and
*which* entity failed. `invariant_from_violations(checker)` builds such an invariant from a
`state -> [problems]` function you already have. And where `check` stops at the first broken rule,
`reachable_violations(model)` lists *every* state-and-rule that breaks — a full audit, e.g. to
enumerate exactly which situations a new guard needs to rule out.

**Concurrency, for free** — give each actor's steps as actions and hand musil all of them. It tries
every available step from every state, so *every interleaving* — every order the concurrent steps
could run in — gets checked. That's how it finds races a normal test would only hit on an unlucky run:

```python
# two non-atomic increments race; musil finds the lost update
check(Model(init=Counter(), actions=[*actor_a, *actor_b], invariants={...}))
```

**Liveness — "something good eventually happens"** — `check_liveness(model, goal=P)`. Where safety is
"nothing bad happens," liveness is "the system never gets stuck short of where it should end up."
`goal=P` asks: does every run *eventually* reach a state where P holds? `everywhere=True` asks the
stronger question — from *any* reachable state, is P always still reachable later? — i.e. the system
always re-converges and can't get trapped.

```python
# every run eventually reaches served == desired; everywhere=True = it always re-converges
check_liveness(model, goal=lambda s: s.served == s.desired, everywhere=True, fair=["reconcile"])
```

When liveness fails, the counterexample is a **lasso**: a path leading into a loop the system can
repeat forever without ever reaching the goal — a straight "stem" into a "cycle," shaped like a lasso.

Some such loops aren't real bugs, because a reasonable scheduler would eventually break out of them.
You say which steps are scheduled fairly: `fair=[...]` assumes **weak fairness** — a step that stays
available throughout the loop must eventually be taken. `fair_strong=[...]` assumes **strong
fairness** — a step that keeps becoming available again and again (even if it flickers off in
between) must eventually be taken; this is what you need to prove, e.g., that a message eventually
gets through a link that randomly drops some. Assume the *least* fairness that makes your property
hold — assuming too much can hide real bugs.

`leadsto_from=Q` checks a **response** property: *whenever Q happens, P eventually follows* — the
everyday "nothing gets stuck" (every service that reaches `placed` eventually reaches `running`).
It's more lenient than `everywhere=True`: a never-reaching-the-goal loop only counts against you if
Q can actually lead into it.

**Compose components & model the network** — `compose(...)` takes several independent component
models and builds the combined system (every way their steps can interleave), carrying over each
component's own rules and letting you add rules about the whole. The channel kit (`channel_actions`,
`send`) models a network link — reliable, lossy (drops messages), or duplicating — and treats
messages as *unordered*, so **every possible reordering is checked for you**. For links that must
preserve order (protocols that number their messages, like the alternating-bit protocol),
`fifo_channel_actions` / `fifo_send` give a first-in-first-out queue with no reordering.

**Keep the model in sync with your code ("zero-drift")** — rather than hand-write the model's steps,
generate them from the *same* allowed-transitions table your code already enforces. Then the model
can't silently disagree with the code, because it *is* the code's table:

```python
from musil import status_field_actions, terminal_states
model = Model(
    init=Service("pending"),
    actions=status_field_actions(ALLOWED["service"]),     # generated from YOUR table
    terminal=lambda s: s.status in terminal_states(ALLOWED["service"]),
)
```

If your state has several such status fields (a control-plane record with `node` / `service` / `cert`
statuses, each with its own table), `multi_status_field_actions({field: table, ...})` builds them all
at once.

**Visualize** — `to_dot(model)` returns a Graphviz diagram (`dot -Tsvg`); pass
`highlight=[s.state for s in result.trace]` to colour the counterexample path.

**Check a system against a hostile environment** — real systems run on top of things that fail at the
worst moment (Kubernetes evicts your pod, AWS throttles you, a disk fills up). `check_open(system,
*envs)` checks your system while an external component misbehaves in *every* way its contract allows.
Each `EnvironmentSpec` is that contract: the *behaviors* it can throw at you (evict, crash, return a
wrong answer), the *guarantees* it still promises to keep, and the *assumptions* those promises rest
on. musil tries every environment action from every reachable state — the worst case, not a sampled
one:

```python
from musil import Assumption, EnvironmentSpec, Action, check_open

k8s = EnvironmentSpec[ServiceState](
    name="k8s",
    behaviors=[Action("k8s:evict-pod", can_evict, do_evict)],
    guarantees={"restarts-non-negative": lambda s: s.restarts >= 0},
    assumptions={"node-capacity": Assumption(
        name="node-capacity",
        description="At least one node is always available after eviction",
        status="unverified", source="Kubernetes docs",
    )},
)

result = check_open(model, k8s)
result.ok                        # did the system survive every possible eviction?
result.unverified_assumptions    # the assumptions you're still trusting on faith (the fine print)
```

`check_open(m)` with no environments is exactly `check(m)`. See
[open-systems.md](https://musil-d34e71.gitlab.io/open-systems/) and `examples/k8s_scheduler.py`.

**Check the real code, not just the design** — `simulate` runs your *actual* event-driven node code
on a simulated network that drops, duplicates, and reorders messages, all driven by a random seed so
each run is exactly reproducible. It holds the code to a model (every step the code takes must be one
the model allows — that's `check_refinement`), plus your invariants and a goal it should settle into.
This is the [FoundationDB](https://apple.github.io/foundationdb/testing.html)/TigerBeetle "deterministic
simulation testing" technique as a pure-Python library — it *finds* bugs (with a seed you can replay),
rather than proving their absence:

```python
from musil import simulate, NetworkModel
report = simulate(node_factory, seeds=range(1000), snapshot=snapshot,
                  network=NetworkModel(loss=0.3, max_latency=3),
                  model=spec, abstraction=lift, goal=lambda w: w.applied == w.desired)
if not report.ok:
    print(report.failure)   # which seed, which step, which world — re-run seeds=[that_seed] to replay
```

To test against components that actively misbehave — "Byzantine" faults, meaning nodes that *lie* or
break the protocol rather than merely crash — `AdversarialNode` injects wrong answers and
`NetworkModel(mutate=...)` corrupts messages in flight. See `examples/byzantine_service.py`.

See **[Verifying a distributed system](https://musil-d34e71.gitlab.io/verifying-distributed-systems/)**
and the runnable [`examples/route_delivery.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/route_delivery.py).

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

- **It enumerates states**, so it's for **bounded** models — a finite, not-too-large number of
  reachable states. Very large or infinite state spaces blow up (cap with `max_states`; the result
  flags `truncated`). Tools that reason symbolically instead of enumerating (TLA+'s Apalache, etc.)
  scale further.
- **Limited reduction of redundant work**: when many concurrent steps are independent, musil still
  explores all their orderings, which can be slow (the standard cure, "partial-order reduction," is
  not implemented). It *can* collapse interchangeable parts of the state — pass `canonicalize=...`
  (symmetry reduction), validated by `symmetry_reduction_sound`.
- **Liveness is fairness-based, not arbitrary temporal logic**: it covers "eventually," "always
  eventually" (with weak and strong fairness), and the "whenever Q then eventually P" response
  property — not every formula a full temporal logic (LTL) could express.
- **It checks the model**, not your code. Whether the real code actually behaves like the model is a
  separate question — `simulate`, or `generate_traces` + `replay`, bridge it by running the model's
  expected behaviors against the code.

## Development & CI

The toolchain is pinned with [proto](https://moonrepo.dev/proto) (`.prototools`: `moon` + `uv`)
and every task is a [moon](https://moonrepo.dev) target running through `uv run`. After cloning:

```
proto install          # installs the pinned moon + uv
moon run :ci           # lint + typecheck + test + build + docs (one task graph)
moon run :test         # or run a single target
make install-hooks     # pre-commit auto-bump + pre-push checks (one-time)
```

CI is a **single GitLab job**: `proto install` brings up the toolchain, then one `moon run`
resolves the whole graph — there are no per-language jobs or hand-wired stages. (`make` targets
still work locally; they call `uv run` directly and don't need moon.)

## Releasing

The version in `pyproject.toml` is the single source of truth, and releases are automated:

1. **`pre-commit` auto-bumps** the patch version whenever a commit touches `src/` (run
   `make install-hooks` once after cloning). Doc/test/example/config-only commits don't bump.
   For an intentional minor/major release, bump deliberately: `make bump TYPE=minor`.
2. **`version-guard`** (the `moon run :version-guard` task, part of `:ci`) enforces the same rule
   non-bypassably in CI: a push or MR that changes `src/` without a version bump fails the pipeline,
   catching `--no-verify` and unhooked clones.
3. **`:release`** runs on a green `main` pipeline (after the full `:ci` graph as deps): if
   `pyproject`'s version isn't on PyPI yet, it publishes via OIDC Trusted Publishing. So merging a
   version bump to `main` releases itself — no second pipeline, no tag required.

### One-time setup

**PyPI — OIDC Trusted Publishing** (no API token is stored anywhere). Account → Publishing → add a
*pending* GitLab publisher (or add it to the project after the first manual upload):

| Field | Value |
|-------|-------|
| PyPI Project Name | `musil` |
| Namespace | `jorgeecardona` |
| Project name (repo) | `musil` |
| Top-level pipeline file | `.gitlab-ci.yml` |
| Environment name | `pypi` |

Publishing uses OIDC Trusted Publishing, so **no token is stored anywhere**. On a green `main`
pipeline, `:release` ships to PyPI whenever `pyproject`'s version isn't published yet — there is no
git tag step.

Releases are automatic on `main` — there is no manual tag or publish step. Pushes and MRs run
lint + typecheck + test + build + docs only.

## License

MIT © Jorge Cardona. See [LICENSE](LICENSE).
