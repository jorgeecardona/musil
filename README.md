# musil

A small, dependency-free **model checker** for Python. You describe a system as *states*, the *steps*
that move between them (each guarded by a condition saying when it can happen), and *invariants*
(rules that must hold in every state). musil then explores every state the system can reach, in
every order concurrent steps can happen, and returns the shortest sequence of steps that
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

The expensive bugs in stateful and distributed systems are temporal and concurrent: a resource
wedged forever, a race that drops data, a deadlock. Tests sample executions; a model checker proves
properties over *all* of them. musil does that in Python, as a library: no separate
spec language, no external binary, no JVM. Your states are frozen dataclasses, your invariants are
predicates, and the whole thing runs in pytest next to your other tests.

The model can be driven from the same data your code uses. Point
`transition_actions` at your real allowed-transitions table and the model can't drift from the code,
because it is built from the code's own table.

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

An invariant returns `True` (holds) or `False` (broken). It may also return a string, meaning
"broken, and here's why" — that text appears in the counterexample, so you learn *which* rule and
*which* entity failed. `invariant_from_violations(checker)` builds such an invariant from a
`state -> [problems]` function you already have. Where `check` stops at the first broken rule,
`reachable_violations(model)` lists *every* state-and-rule that breaks — a full audit, e.g. to
enumerate which situations a new guard needs to rule out.

The flagship example is model checking's most cited success: `check` on the Needham-Schroeder
public-key protocol returns Gavin Lowe's 1995 man-in-the-middle attack as an authentication
counterexample, and proves the fix clean. See `examples/needham_schroeder.py`.

**Concurrency, for free** — give each actor's steps as actions and hand musil all of them. It tries
every available step from every state, so every interleaving (every order the concurrent steps
could run in) gets checked. That's how it finds races a normal test would only hit on an unlucky run:

```python
# two non-atomic increments race; musil finds the lost update
check(Model(init=Counter(), actions=[*actor_a, *actor_b], invariants={...}))
```

**Liveness — "something good eventually happens"** — `check_liveness(model, goal=P)`. Where safety is
"nothing bad happens," liveness is "the system never gets stuck short of where it should end up."
`goal=P` checks that every run *eventually* reaches a state where P holds. `everywhere=True` is
stronger: on every run, P must *always eventually* be reached again — the system re-converges no
matter where a run has gotten to. Note this demands more than P merely staying *reachable*: a loop
that forever declines an available exit toward P is a violation (name that exit in `fair=[...]` if
a fair scheduler would take it eventually). For the plain reachability question — "from which
states can the system still get to P?" — use `reaches`:

```python
# every run eventually reaches served == desired; everywhere=True = it always re-converges
check_liveness(model, goal=lambda s: s.served == s.desired, everywhere=True, fair=["reconcile"])

# weaker: no reachable state is ever *trapped* away from the goal (the goal stays reachable)
g = explore(model)
assert reaches(g, lambda s: s.served == s.desired) == set(g.states)
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

**Arbitrary temporal properties (LTL)** — `check_ltl(model, formula)`. Beyond the fixed forms above, state
any linear-temporal-logic property as data: `Always`, `Eventually`, `Next`, `Until`, `Release`, and boolean
combinations of `Atom`s. The shapes that reduce onto `check` / `check_liveness` take that proven path;
everything else (`Next`, `Until`, nesting) is decided by a general Büchi automaton over the reachable graph.
A violation comes back as a lasso counterexample with a `--- loops forever ---` marker showing which suffix
repeats. The `patterns` helpers (`always`, `eventually`, `recurs`, `responds`) name the common shapes as
one-liners over the same engine. See `examples/ltl_properties.py`.

**Exact quantitative checking (DTMC / MDP)** — `musil.probabilistic`. When actions carry a relative
probability weight, the reachable graph is a Markov chain and you can ask exact questions, answered as
`fractions.Fraction` with no floating-point error — verification, not the sampling `sim` does:

- **Reachability** — `reach_probability` (eventually, within `steps=k`, or the until-property
  `P(¬avoid U target)`) and `expected_reward` (expected steps/cost to reach a target, bounded or unbounded).
- **Steady state and transient** — `long_run_probability` / `long_run_reward` (the long-run fraction of time
  in a set, or the long-run average of a reward rate), and `transient_distribution` (the exact state
  distribution after exactly `k` steps).
- **Probabilistic LTL** — `probability_ltl` (the probability a random run satisfies `F` / `G` / `GF` / `FG` of
  a state predicate, or the until `a U b` / release `a R b` / weak-until `a W b` of two state predicates —
  constrained reachability and its duals).
- **Nondeterminism (MDP)** — every one of the above has an `..._mdp` form (or a `moves=` argument) giving the
  minimum or maximum over all schedulers.

Everything is exact rational arithmetic — assert on it in tests with `assert_probability(p, at_most=Fraction(1,
100))` (thresholds, ranges, or exact equality, with a clear failure message). See `examples/monty_hall.py`
(the exact 2/3 result), `examples/gamblers_ruin.py` (the canonical random walk), `examples/lossy_retry.py`,
`examples/availability.py`, and `examples/server_utilization.py`.

**Where does it settle? — confluence** — `fixed_points(model)` reports, for each initial state
*separately*, the distinct terminal states (no available step) its runs can end in. A single start
that can settle in two different places means the outcome depends on the order steps fired — e.g.
an event-iteration loop whose fixed point silently depends on which pending event is applied first.
`fixed_points(model).confluent` asserts no start has that choice. Different starts settling in
different places is fine (that's what a latch is *for*); a start with an empty set never settles at
all, which is a liveness question, not a confluence one.

**Reading results in assertions** — `print(result)` renders the verdict; in test assertions, use
the fields (both result types are truthy exactly when `ok`):

`check` → `Result`:

| field | meaning |
|---|---|
| `ok` | `True` when every reachable state passed every invariant and nothing deadlocked |
| `kind` | `None` on success, else `"invariant"` or `"deadlock"` |
| `invariant` | name of the broken invariant (when `kind == "invariant"`) |
| `reason` | the text a string-returning invariant produced, if any |
| `trace` | shortest path to the offending state — a tuple of `Step`, each with `.action` and `.state` |
| `states_explored` | how many states the sweep visited |
| `truncated` | `True` if the `max_states` cap stopped the sweep before exhausting the space |

`check_liveness` → `LivenessResult`:

| field | meaning |
|---|---|
| `ok` | `True` when the property holds on every run |
| `kind` | `None` on success, else `"p-unreachable"` or `"fair-cycle"` |
| `goal` | the `goal_name` you passed, used in rendering |
| `stem` | shortest path from an initial state to the offending state or loop (`Step` tuple) |
| `cycle` | the loop the system can repeat forever (empty when `kind == "p-unreachable"`) |
| `states_explored`, `truncated` | as above |

**Compose components & model the network** — `compose(...)` takes several independent component
models and builds the combined system (every way their steps can interleave), carrying over each
component's own rules and letting you add rules about the whole. The channel kit (`channel_actions`,
`send`) models a network link — reliable, lossy (drops messages), or duplicating — and treats
messages as *unordered*, so every possible reordering is checked for you. For links that must
preserve order (protocols that number their messages, like the alternating-bit protocol),
`fifo_channel_actions` / `fifo_send` give a first-in-first-out queue with no reordering.

**Keep the model in sync with your code ("zero-drift")** — rather than hand-write the model's steps,
generate them from the same allowed-transitions table your code already enforces. Then the model
can't silently disagree with the code, because it is the code's table:

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
on. musil tries every environment action from every reachable state, covering the worst case rather
than a sample:

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
each run is reproducible. It holds the code to a model (every step the code takes must be one
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

To test against components that actively misbehave ("Byzantine" faults: nodes that lie or
break the protocol rather than merely crash), `AdversarialNode` injects wrong answers and
`NetworkModel(mutate=...)` corrupts messages in flight. See `examples/byzantine_service.py`.

See [Verifying a distributed system](https://musil-d34e71.gitlab.io/verifying-distributed-systems/)
and the runnable [`examples/route_delivery.py`](https://gitlab.com/jorgeecardona/musil/-/blob/main/examples/route_delivery.py).

## How it compares

| | what it is | spec language | runs the real code? | liveness |
|---|---|---|---|---|
| **musil** | in-Python library, explicit-state | Python (frozen dataclasses) | the model can be driven from your code's tables | full LTL + weak/strong-fairness liveness + exact DTMC/MDP probabilities |
| TLA+ / TLC | standalone checker | TLA+ (math) | no (separate model) | full temporal logic |
| P | DSL + systematic testing, compiles to C | P (state machines) | yes (executable model) | safety + liveness |
| Stateright | Rust library, model-check + run | Rust | yes (same actors on a real network) | safety + liveness |
| FizzBee | Go binary, Python-like DSL | `.fizz` | no | safety + basic liveness |

musil is the smallest member of this family: pick it when your state space is bounded and small,
you want the model *in* your test suite with zero new tooling, and the win is catching races /
deadlocks / stuck states and proving convergence.

## Limitations

- **It enumerates states**, so it's for bounded models — a finite, not-too-large number of
  reachable states. Very large or infinite state spaces blow up (cap with `max_states`; the result
  flags `truncated`). Tools that reason symbolically instead of enumerating (TLA+'s Apalache, etc.)
  scale further. One escape hatch, on the *depth* axis: `check_inductive` proves an invariant by
  k-induction over the transition relation, so a pass holds at unbounded depth (every reachable
  state, not just the explored scope) — but it still enumerates a bounded `domain` of candidate
  states, so an infinite value domain or an unbounded number of components still needs a symbolic
  solver. It moves the bound from *depth* to *state variables*, it doesn't remove it.
- **Exact search by design, never approximate.** A clean `check` is a proof that the *whole* reachable space
  was swept. musil deliberately has no approximate-search mode (SPIN's supertrace / bitstate hash-compaction):
  those trade a nonzero chance of missing a state for reaching larger spaces, and a checker whose "OK" might
  have skipped the one bug is not what musil is for. (The probabilistic layer is a different thing — it
  computes *exact* rational probabilities over the full graph, no sampling.) Every reduction musil *does*
  offer (symmetry, footprint memoization) ships behind a gate that proves no state was dropped. If RAM is the
  ceiling, the answer is lossless (compress the stored states, or spill them to disk), never a miss. See
  `BITSTATE_NOTES.md`.
- **Reducing redundant interleavings is opt-in, not automatic**: when many concurrent steps are independent,
  the default sweep still explores all their orderings. Partial-order reduction *is* available —
  `explore_por(model, ample=...)` fires only a chosen subset per state, and `por_sound` validates that the
  choice drops no reachable violation — but computing the ample set automatically is deferred (see
  `REDUCTION_NOTES.md`), so today you supply and gate it. Interchangeable parts of the state collapse with
  `canonicalize=...` (symmetry reduction), validated by `symmetry_reduction_sound`.
- **It checks the model**, not your code. Whether the real code actually behaves like the model is a
  separate question — `simulate`, or `generate_traces` + `replay`, bridge it by running the model's
  expected behaviors against the code.

## Contributing

Toolchain, CI, and the release process live in
[CONTRIBUTING.md](https://gitlab.com/jorgeecardona/musil/-/blob/main/CONTRIBUTING.md). In short: `proto install`
then `moon run :ci` (lint + typecheck + test + build + docs), and releases publish themselves from a green
`main` pipeline.

## License

MIT © Jorge Cardona. See [LICENSE](LICENSE).
