"""VOPR-style liveness: does the system converge once a fault HEALS?

The FoundationDB/TigerBeetle simulation-testing question isn't just "is it safe?" but "does it make
progress?" -- after the network heals, does the replica actually catch up? musil's `simulate` injects
a *sustained, heal-able* fault from a `FaultSchedule` and then asserts convergence once it lifts. A
plain random-loss `NetworkModel` can't express this: independent per-message loss self-heals via
retries. A partition or a crash is different -- the system can only recover after it ends.

A source pushes a value to a replica; the goal is `applied == desired` once things settle.

  * PARTITION the s->r link for a window, then heal:
      - fire-and-forget (one push, no retry) -> the partition eats the only push -> WEDGED forever.
      - per-tick re-push                      -> the first push after the heal lands -> CONVERGES.
  * CRASH the replica with a cold restart (it loses state):
      - with no re-push, an already-acked value is gone after restart -> LOST ON RESTART.

Each failure is a `kind="liveness"` report carrying a reproducing seed.

Run me:  python examples/partition_heal.py
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from musil.sim import BaseNode, Context, Crash, FaultSchedule, Node, Partition, SimReport, simulate


class Source(BaseNode):
    """Pushes the desired value to the replica; with ``repush`` it re-sends on a timer until acked."""

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
    """Applies the largest value it has seen and acks. A cold restart wipes ``applied`` back to 0."""

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
    s, r = nodes["s"], nodes["r"]
    assert isinstance(s, Source) and isinstance(r, Replica)
    return World(desired=s.desired, applied=r.applied)


def _factory(repush: bool) -> Callable[[], Mapping[str, Node]]:
    def make() -> Mapping[str, Node]:
        return {"s": Source(repush=repush), "r": Replica()}

    return make


def _converges(repush: bool, faults: FaultSchedule) -> SimReport[World]:
    return simulate(
        _factory(repush=repush),
        seeds=range(50),
        snapshot=_snapshot,
        faults=faults,
        goal=lambda w: w.applied == w.desired,
        goal_name="applied==desired",
    )


def main() -> int:
    print("VOPR-style liveness -- converge after the fault heals?\n")

    partition = FaultSchedule(partitions=(Partition(frozenset({("s", "r")}), start=0, end=10),))
    faf = _converges(repush=False, faults=partition)
    assert not faf.ok and faf.failure is not None
    print(f"  partition + fire-and-forget : WEDGED  (kind={faf.failure.kind}, seed={faf.failure.seed})")

    rep = _converges(repush=True, faults=partition)
    assert rep.ok, str(rep)
    print(f"  partition + per-tick re-push: CONVERGES ({rep.runs} seeds, all green)")

    crash = FaultSchedule(crashes=(Crash(node="r", start=3, end=8, lose_state=True),))
    lost = _converges(repush=False, faults=crash)
    assert not lost.ok and lost.failure is not None
    print(f"  crash (cold restart)        : LOST ON RESTART (kind={lost.failure.kind}, seed={lost.failure.seed})")

    print("\nOnly the retrying system survives a heal; a cold restart loses an un-retried write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
