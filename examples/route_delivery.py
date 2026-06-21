"""Verify a distributed protocol end to end, in pure Python -- design AND implementation.

The story: a control plane pushes a route-table version to an agent over a flaky link; the agent
applies last-writer-wins. We want two guarantees:

  * SAFETY  -- the agent never serves a version the control plane never intended.
  * LIVENESS -- the agent always eventually catches up to the latest version (convergence).

Two layers, one tool:

  1. DESIGN (model check) -- `musil.check` / `check_liveness` exhaustively verify the *design* (a
     small state machine) for safety and convergence-under-fairness.

  2. IMPLEMENTATION (deterministic simulation) -- `musil.simulate` runs the *real* node code under a
     lossy, reordering network across many seeds, holding it to the SAME model (refinement) and to
     the convergence goal. The buggy fire-and-forget push is caught with a reproducible seed; the
     per-tick re-push converges for every seed.

Run me:  python examples/route_delivery.py
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from musil import (
    Action,
    BaseNode,
    Context,
    Model,
    NetworkModel,
    Node,
    check,
    check_liveness,
    simulate,
)

# ----------------------------------------------------------------------------------------------------
# 1. The design, as a model. One route version is desired; the agent's applied version trails it.
# ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    desired: int = 1
    applied: int = 0


def build_model() -> Model[Spec]:
    return Model(
        init=Spec(desired=1, applied=0),
        actions=[
            # the network delivers the pushed version; the agent applies it (last-writer-wins)
            Action("deliver", lambda s: s.applied < s.desired, lambda s: Spec(s.desired, s.desired)),
        ],
        invariants={"no-stale-or-invented": lambda s: s.applied <= s.desired},
        terminal=lambda s: s.applied == s.desired,
    )


def check_design() -> tuple[bool, bool]:
    """Model-check the design: safety (the invariant, no deadlock) and convergence under fair delivery."""
    safety = check(build_model())
    liveness = check_liveness(
        build_model(),
        goal=lambda s: s.applied == s.desired,
        goal_name="applied==desired",
        everywhere=True,
        fair=["deliver"],
    )
    return safety.ok, liveness.ok


# ----------------------------------------------------------------------------------------------------
# 2. The implementation, as real event-driven nodes.
# ----------------------------------------------------------------------------------------------------


class ControlPlane(BaseNode):
    """Pushes the desired version to the agent. With ``repush`` it re-sends on a timer until acked;
    without it (fire-and-forget), the single push is all the agent will ever get."""

    def __init__(self, *, repush: bool) -> None:
        self.desired = 1
        self._repush = repush
        self._acked = False

    def on_start(self, ctx: Context) -> None:
        ctx.send("agent", self.desired)
        if self._repush:
            ctx.set_timer("push", delay=2)

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "ack":
            self._acked = True

    def on_timer(self, ctx: Context, name: str) -> None:
        if self._repush and not self._acked:
            ctx.send("agent", self.desired)
            ctx.set_timer("push", delay=2)


class Agent(BaseNode):
    """Applies the latest version it has seen and acks."""

    def __init__(self) -> None:
        self.applied = 0

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        assert isinstance(payload, int)
        self.applied = max(self.applied, payload)
        ctx.send(src, "ack")


def _snapshot(nodes: Mapping[str, Node]) -> Spec:
    cp, agent = nodes["cp"], nodes["agent"]
    assert isinstance(cp, ControlPlane) and isinstance(agent, Agent)
    return Spec(desired=cp.desired, applied=agent.applied)


def _factory(repush: bool) -> Callable[[], Mapping[str, Node]]:
    def make() -> Mapping[str, Node]:
        return {"cp": ControlPlane(repush=repush), "agent": Agent()}

    return make


# a link that drops ~30% of messages and reorders the rest
_LOSSY = NetworkModel(loss=0.3, min_latency=1, max_latency=3)


def run_fire_and_forget(seeds: range = range(300)):  # noqa: B008
    return simulate(
        _factory(repush=False),
        seeds=seeds,
        snapshot=_snapshot,
        network=_LOSSY,
        model=build_model(),
        abstraction=lambda s: s,
        goal=lambda s: s.applied == s.desired,
        goal_name="applied==desired",
    )


def run_repush(seeds: range = range(300)):  # noqa: B008
    return simulate(
        _factory(repush=True),
        seeds=seeds,
        snapshot=_snapshot,
        network=_LOSSY,
        model=build_model(),
        abstraction=lambda s: s,
        goal=lambda s: s.applied == s.desired,
        goal_name="applied==desired",
    )


def main() -> int:
    print("=== DESIGN (model check) ===")
    safety_ok, liveness_ok = check_design()
    print(f"  safety (no stale/invented version, no deadlock): {'OK' if safety_ok else 'FAIL'}")
    print(f"  liveness (converges under fair delivery):        {'OK' if liveness_ok else 'FAIL'}")

    print("\n=== IMPLEMENTATION (deterministic simulation, lossy network) ===")
    ff = run_fire_and_forget()
    print("  fire-and-forget push:")
    if ff.ok:
        print(f"    converged on all {ff.runs} seeds (unexpected!)")
    else:
        assert ff.failure is not None
        print(f"    BUG FOUND -- {ff.failure.kind} on seed {ff.failure.seed}: {ff.failure.detail}")
        print(f"    final world: {ff.failure.world}  (reproduce with seeds=[{ff.failure.seed}])")

    rp = run_repush()
    print("  per-tick re-push:")
    if rp.ok:
        print(f"    converged AND refined the model on all {rp.runs} seeds")
    else:
        assert rp.failure is not None
        print(f"    unexpected failure: {rp.failure}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
