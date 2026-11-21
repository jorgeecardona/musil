# Open systems

musil's `check()` assumes a **closed system**: every action in the model is yours. The state
machine controls its own fate. Real distributed software lives in an open world: Kubernetes can
evict your pod mid-request, AWS S3 can return a 503, a Byzantine peer can send wrong data.
`check_open()` brings those adversaries into the proof.

## Closed vs. open

| Dimension | Closed (`check`) | Open (`check_open`) |
|-----------|-----------------|---------------------|
| Environment | Part of the model | External, adversarial |
| Assumptions | None (all behaviour is specified) | Explicit, named, layered |
| Guarantee | Holds for all traces of the model | Holds given stated assumptions |
| API | `check(model)` | `check_open(system, *envs)` |

The key shift: instead of pretending the environment is cooperative (or ignoring it), you write
down what the environment *can* do and what you *assume* it won't do. The BFS explores every
adversarial move. The residual obligations (the assumptions you couldn't prove) surface in the
result rather than hiding in comments.

## The `EnvironmentSpec` contract

```python
from musil import Action
from musil.env import Assumption, EnvironmentSpec

k8s = EnvironmentSpec[ServiceState](
    name="k8s",
    behaviors=[
        # what K8s can do to your pod
        Action("k8s:evict-pod", can_evict, do_evict),
    ],
    guarantees={
        # what K8s commits to (becomes an invariant in the composed check)
        "restarts-non-negative": lambda s: s.restarts >= 0,
    },
    assumptions={
        # what you take on faith (printed as residual obligations)
        "node-capacity": Assumption(
            name="node-capacity",
            description="At least one schedulable node is always available after eviction",
            status="unverified",
            source="Kubernetes docs: Pod lifecycle",
        ),
    },
)
```

An `EnvironmentSpec` has three parts:

**`behaviors`**: the adversarial actions the environment can take. Each is a plain `Action[S]`,
so the guard decides *when* the environment may act and the transition decides *what it does*.
The BFS treats these exactly like system actions. It tries every enabled behavior at every
reachable state, so the analysis is adversarial, not optimistic.

**`guarantees`**: invariants the environment commits to. `check_open` folds these into the
composed model's invariants, qualified as `"<env.name>:<key>"`. If a guarantee is violated, the
result names the broken commitment (e.g., `"k8s:restarts-non-negative"`).

**`assumptions`**: named proof obligations. An assumption has a `status`:
- `"unverified"`: not yet proven, should be tracked
- `"axiom"`: taken as a ground truth (e.g., hardware memory safety)
- `"verified"`: proven by some other means (excluded from the residual list)

Both `"unverified"` and `"axiom"` assumptions appear in `OpenResult.unverified_assumptions`.
This follows seL4's two-layer assurance model (Klein et al., SOSP 2009): formal guarantees hold
*given* the stated assumptions, and the assumptions are first-class, not footnotes.

## Running `check_open`

```python
from musil import check
from musil.env import check_open

model = _service_model()

# closed: no environment, same as check()
result = check_open(model)
assert result == check(model)  # equivalent

# open: BFS explores every K8s eviction timing
result = check_open(model, k8s)

if result.ok:
    print("Safe under all K8s behaviours")
else:
    print(f"Violated: {result.result.invariant}")
    print(f"Counterexample: {result.result.trace}")

# residual proof obligations
for a in result.unverified_assumptions:
    print(f"[{a.status}] {a.name}: {a.description}")
```

`check_open` composes environments by merging their behaviors into the system's action set
and their guarantees into the invariants. With multiple environments, pass them all:

```python
result = check_open(model, k8s, aws, linux)
```

Each environment's behaviors are explored independently. The BFS considers any combination of
adversarial moves from any environment at any reachable state.

## When to use `check_open` vs. `check`

Use `check` when:
- All state transitions are under your control
- You want to verify a protocol design in isolation
- There is no meaningful external component to model

Use `check_open` when:
- The system runs inside a platform that can fault (K8s, AWS, Linux, seL4)
- You need to verify your system handles adversarial external inputs
- You want a structured record of what you're assuming about the environment

Both use the same BFS engine. `check_open(model)` with no environments is exactly `check(model)`.

## Writing a good `EnvironmentSpec`

**Be specific about guards.** An environment action with `guard=lambda s: True` is maximally
adversarial. It fires at every state, including states where the real environment would never act.
For K8s eviction, `can_evict = lambda s: s.status in {"healthy", "degraded"}` is more faithful:
K8s can only evict a running pod.

**Model one outcome per action.** If K8s pod eviction can either restart the pod or leave it
unresponsive depending on configuration, model two separate actions (`evict_restart` and
`evict_kill`) each with its own guard and transition. Let the BFS find the one that violates your
invariant.

**State assumptions, don't hide them.** If your system only stays correct because K8s always
reschedules within 30 seconds, write that as an `Assumption(status="unverified")`. Don't model it
as a constraint that silently bounds the BFS.

**Distinguish axioms from unverified claims.** Hardware memory safety is an axiom. You can't
prove it, but you accept it as a foundation. A cloud SLA is unverified. You should track it and
eventually measure or document it. Using `status="axiom"` vs `status="unverified"` makes the
distinction explicit.

## Simulation: `AdversarialNode` and `NetworkModel.mutate`

For simulation testing (message-passing, not global-state BFS), musil provides two injection
points:

**`AdversarialNode`**: a `BaseNode` that routes messages through `(guard, response)` pairs.
The first matching guard fires its response; no match drops the message silently. Use it to
model an external service that returns wrong answers:

```python
from musil.sim import AdversarialNode, Context

wrong_answer_service = AdversarialNode(
    behaviors=[
        (
            lambda src, payload: payload == "query",
            lambda ctx, src, payload: ctx.send(src, -1),  # wrong answer
        ),
    ]
)
```

**`NetworkModel.mutate`**: a `Callable[[src, dst, payload], object | None]` hook on
`NetworkModel`. Applied after loss/duplicate decisions, before delivery. Return `None` to
drop the message; return a modified payload to corrupt it:

```python
from musil.sim import NetworkModel

def corrupt(src: str, dst: str, payload: object) -> object | None:
    if isinstance(payload, int):
        return f"corrupted:{payload}"  # type corruption
    return payload

net = NetworkModel(mutate=corrupt)
```

See `examples/byzantine_service.py` for worked scenarios of both.

## Academic grounding

| musil concept | Academic source |
|---------------|----------------|
| `EnvironmentSpec.behaviors` | TLA+ open-system non-determinism (Newcombe et al., CACM 2015) |
| `Assumption` with explicit status | seL4 two-layer assurance (Klein et al., SOSP 2009) |
| `check_open` composition | Interface Automata (de Alfaro & Henzinger, ESEC/FSE 2001) |
| `(assumptions, guarantees)` pair | Contract-based design (Benveniste et al., INRIA RR-8147, 2012) |
| Action partitioning (env vs. system) | I/O Automata (Lynch & Tuttle, 1987) |
| `AdversarialNode` power bounds | Byzantine Generals (Lamport, Shostak & Pease, TOPLAS 1982) |
| Payload `mutate` hook | Byzantine fault injection (Castro & Liskov, OSDI 1999) |
