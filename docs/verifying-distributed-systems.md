# Verifying a distributed system

musil gives you two layers, in pure Python, that fit together:

1. **Model-check the design** — describe the protocol as a state machine and prove (over a bounded
   state space) that it is safe and converges. This is the [TLA+](https://lamport.azurewebsites.net/tla/tla.html)
   job: find the *design* bugs.
2. **Deterministic simulation testing of the real code** — run your *actual* node logic under a
   controlled clock and a fault-injecting network, reproducibly from a seed, and hold it to the same
   model. This is the [FoundationDB](https://apple.github.io/foundationdb/testing.html) /
   [TigerBeetle](https://tigerbeetle.com/) job: find the *implementation* bugs.

It is **bug-finding, not proof.** A clean run of a bounded model and a few thousand seeds is strong
evidence, not a theorem (that's theorem-prover territory — Isabelle/Coq/Dafny, person-years). But it
is the same technique the most reliable distributed systems in the world are built with.

!!! note "What this is not"
    musil is explicit-state and bounded: it enumerates a finite model and samples real-code schedules.
    It does not prove correctness for unbounded scale, and it only finds faults you model. Model the
    network explicitly, bound your state, and lean on the small-scope hypothesis.

## 1. Model-check the design

A control plane pushes a route version to an agent; the agent applies last-writer-wins. Safety: never
apply a version that wasn't intended. Liveness: always eventually catch up.

```python
from dataclasses import dataclass
from musil import Action, Model, check, check_liveness

@dataclass(frozen=True)
class Spec:
    desired: int = 1
    applied: int = 0

def model() -> Model[Spec]:
    return Model(
        init=Spec(desired=1, applied=0),
        actions=[Action("deliver", lambda s: s.applied < s.desired, lambda s: Spec(s.desired, s.desired))],
        invariants={"no-stale-or-invented": lambda s: s.applied <= s.desired},
        terminal=lambda s: s.applied == s.desired,
    )

assert check(model()).ok                                   # safety + no deadlock
assert check_liveness(model(), goal=lambda s: s.applied == s.desired,
                      everywhere=True, fair=["deliver"]).ok  # converges under fair delivery
```

## 2. Simulate the real code

Now the *implementation*: event-driven nodes that send messages, set timers, and read a virtual
clock through a [`Context`][musil.sim.Context]. `simulate` runs them across many seeds under a
[`NetworkModel`][musil.sim.NetworkModel], checking invariants and refinement after every step and a
convergence goal once each run settles.

```python
from collections.abc import Mapping
from musil import BaseNode, Context, NetworkModel, Node, simulate

class ControlPlane(BaseNode):
    def __init__(self, *, repush: bool) -> None:
        self.desired, self._repush, self._acked = 1, repush, False
    def on_start(self, ctx: Context) -> None:
        ctx.send("agent", self.desired)
        if self._repush:
            ctx.set_timer("push", delay=2)
    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        self._acked = self._acked or payload == "ack"
    def on_timer(self, ctx: Context, name: str) -> None:
        if self._repush and not self._acked:
            ctx.send("agent", self.desired)
            ctx.set_timer("push", delay=2)

class Agent(BaseNode):
    def __init__(self) -> None:
        self.applied = 0
    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        assert isinstance(payload, int)
        self.applied = max(self.applied, payload)
        ctx.send(src, "ack")

def snapshot(nodes: Mapping[str, Node]) -> Spec:
    return Spec(desired=nodes["cp"].desired, applied=nodes["agent"].applied)  # type: ignore[attr-defined]

def factory(repush: bool):
    return lambda: {"cp": ControlPlane(repush=repush), "agent": Agent()}

lossy = NetworkModel(loss=0.3, min_latency=1, max_latency=3)

# fire-and-forget: a dropped push is never re-sent -> the agent never catches up
bad = simulate(factory(repush=False), seeds=range(300), snapshot=snapshot, network=lossy,
               goal=lambda s: s.applied == s.desired)
assert not bad.ok
print(bad.failure)   # GOAL on seed 1 ...  reproduce with seeds=[1]

# per-tick re-push: converges, and refines the model, on every seed
good = simulate(factory(repush=True), seeds=range(300), snapshot=snapshot, network=lossy,
                model=model(), abstraction=lambda s: s, goal=lambda s: s.applied == s.desired)
assert good.ok
```

When a seed fails, [`SimFailure`][musil.sim.SimFailure] tells you exactly which one — re-run with
`seeds=[that_seed]` and the run replays bit-for-bit, because the whole simulation is a deterministic
function of the seed. That is the property that makes simulation testing debuggable.

Here is the full, runnable example in one piece — run it with `python examples/route_delivery.py`:

```python
--8<-- "examples/route_delivery.py"
```

## The faults you can inject

[`NetworkModel`][musil.sim.NetworkModel] controls the link: `loss` (drop probability), `duplicate`
(redelivery probability), and a `min_latency`/`max_latency` spread (latency variance is what produces
**reordering** and delay). The default is a reliable, in-order channel — faults are opt-in, so you
turn on exactly the adversity you want to test against. Timers (`ctx.set_timer`) let nodes detect and
recover from loss; the seeded clock makes timeouts fire deterministically.
