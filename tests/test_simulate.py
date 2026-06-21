"""simulate(): run the real nodes across many seeds under faults, with invariants + refinement as the
oracle, and report the first failing seed (a reproducible repro). This is where design model-checking
(musil.check) and the real code meet: the SAME model is the spec the simulated implementation is held
to, and convergence (a goal that must hold once the system settles) is checked end-to-end."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from musil import Action, Model
from musil.sim import BaseNode, Context, NetworkModel, Node, simulate


class Source(BaseNode):
    """Holds the desired value; pushes it to the replica. If repush, re-sends on a timer until acked."""

    def __init__(self, *, repush: bool) -> None:
        self.desired = 1
        self._repush = repush
        self._acked = False

    def on_start(self, ctx: Context) -> None:
        ctx.send("r", self.desired)
        if self._repush:
            ctx.set_timer("push", delay=2)

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "ack":
            self._acked = True

    def on_timer(self, ctx: Context, name: str) -> None:
        if self._repush and not self._acked:
            ctx.send("r", self.desired)
            ctx.set_timer("push", delay=2)


class Replica(BaseNode):
    """Applies the latest value it has seen (last-writer-wins by value); acks."""

    def __init__(self) -> None:
        self.applied = 0

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        assert isinstance(payload, int)
        self.applied = max(self.applied, payload)
        ctx.send(src, "ack")


@dataclass(frozen=True)
class World:
    desired: int
    applied: int


def _snapshot(nodes: Mapping[str, Node]) -> World:
    src = nodes["s"]
    rep = nodes["r"]
    assert isinstance(src, Source) and isinstance(rep, Replica)
    return World(desired=src.desired, applied=rep.applied)


def _factory(repush: bool) -> object:
    def make() -> Mapping[str, Node]:
        return {"s": Source(repush=repush), "r": Replica()}

    return make


_LOSSY = NetworkModel(loss=0.4, min_latency=1, max_latency=3)


def test_fire_and_forget_loses_the_update_under_loss() -> None:
    # no re-push: some seed drops the single push and the replica never catches up -> goal fails
    report = simulate(
        _factory(repush=False),  # type: ignore[arg-type]
        seeds=range(200),
        snapshot=_snapshot,
        network=_LOSSY,
        goal=lambda w: w.applied == w.desired,
        goal_name="applied==desired",
    )
    assert not report.ok
    assert report.failure is not None
    assert report.failure.kind == "goal"
    # the failure carries the exact seed to reproduce
    assert isinstance(report.failure.seed, int)


def test_per_tick_repush_always_converges_under_loss() -> None:
    # with bounded re-push the replica always catches up, for every seed
    report = simulate(
        _factory(repush=True),  # type: ignore[arg-type]
        seeds=range(200),
        snapshot=_snapshot,
        network=_LOSSY,
        goal=lambda w: w.applied == w.desired,
        goal_name="applied==desired",
    )
    assert report.ok, str(report)
    assert report.runs == 200


def test_safety_invariant_violation_is_caught_with_a_seed() -> None:
    # an invariant that the system actually breaks (applied should never exceed desired, but a buggy
    # replica that doubles the value will) -> caught, with the seed and the offending world
    class BadReplica(BaseNode):
        def __init__(self) -> None:
            self.applied = 0

        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            assert isinstance(payload, int)
            self.applied = payload * 2  # bug: invents a larger value

    def make() -> Mapping[str, Node]:
        return {"s": Source(repush=False), "r": BadReplica()}

    def snap(nodes: Mapping[str, Node]) -> World:
        s, r = nodes["s"], nodes["r"]
        assert isinstance(s, Source) and isinstance(r, BadReplica)
        return World(desired=s.desired, applied=r.applied)

    report = simulate(
        make,
        seeds=range(50),
        snapshot=snap,
        invariants={"no-invented-value": lambda w: w.applied <= w.desired},
    )
    assert not report.ok
    assert report.failure is not None
    assert report.failure.kind == "invariant"
    assert report.failure.detail == "no-invented-value"
    assert report.failure.world.applied > report.failure.world.desired


def _model() -> Model[World]:
    # desired is fixed at 1; applied goes 0 -> 1 by delivery; never exceeds desired
    return Model(
        init=World(desired=1, applied=0),
        actions=[Action("deliver", lambda w: w.applied < w.desired, lambda w: World(w.desired, w.desired))],
        terminal=lambda w: w.applied == w.desired,
    )


def test_a_correct_run_refines_the_model() -> None:
    report = simulate(
        _factory(repush=True),  # type: ignore[arg-type]
        seeds=range(50),
        snapshot=_snapshot,
        network=NetworkModel(),  # reliable: it will converge and stay within the model
        model=_model(),
        abstraction=lambda w: w,
        goal=lambda w: w.applied == w.desired,
    )
    assert report.ok, str(report)
