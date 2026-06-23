"""Deterministic simulation core: run real node code under a controlled scheduler, virtual clock, and
a network that can lose / duplicate / reorder messages -- all from a single seed, so every run is
reproducible. This is the FoundationDB/TigerBeetle "deterministic simulation testing" idea as a pure-
Python library; musil.refine + invariants are the oracle (wired in the next slice)."""

from __future__ import annotations

from musil.sim import BaseNode, Context, Crash, FaultSchedule, NetworkModel, Partition, Simulator


class Pinger(BaseNode):
    """Sends one ping on start; counts pongs."""

    def __init__(self) -> None:
        self.pongs = 0

    def on_start(self, ctx: Context) -> None:
        ctx.send("b", "ping")

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "pong":
            self.pongs += 1


class Ponger(BaseNode):
    """Replies pong to every ping; counts pings."""

    def __init__(self) -> None:
        self.pings = 0

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "ping":
            self.pings += 1
            ctx.send(src, "pong")


def _ping_pong(seed: int = 0, network: NetworkModel | None = None) -> tuple[Simulator, Pinger, Ponger]:
    a, b = Pinger(), Ponger()
    sim = Simulator({"a": a, "b": b}, seed=seed, network=network)
    return sim, a, b


def test_reliable_network_delivers_the_round_trip() -> None:
    sim, a, b = _ping_pong(seed=1)
    result = sim.run()
    assert b.pings == 1
    assert a.pongs == 1
    assert result.reason == "quiescent"
    assert result.delivered == 2  # ping + pong


def test_total_loss_delivers_nothing() -> None:
    sim, a, b = _ping_pong(seed=1, network=NetworkModel(loss=1.0))
    sim.run()
    assert b.pings == 0
    assert a.pongs == 0


def test_runs_are_reproducible_from_the_seed() -> None:
    # same seed + same system -> identical observable outcome, every time
    def outcome(seed: int) -> tuple[int, int, int]:
        sim, a, b = _ping_pong(seed=seed, network=NetworkModel(loss=0.5, min_latency=1, max_latency=5))
        r = sim.run()
        return a.pongs, b.pings, r.delivered

    assert outcome(7) == outcome(7)
    assert outcome(7) == outcome(7)


class Collector(BaseNode):
    """Records the order payloads arrive in."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        assert isinstance(payload, int)
        self.seen.append(payload)


class Burst(BaseNode):
    """Fires a burst of numbered messages at the collector on start."""

    def __init__(self, n: int) -> None:
        self.n = n

    def on_start(self, ctx: Context) -> None:
        for i in range(self.n):
            ctx.send("c", i)


def test_constant_latency_preserves_fifo_order() -> None:
    c = Collector()
    sim = Simulator({"s": Burst(5), "c": c}, seed=3)  # default network: reliable, latency 1
    sim.run()
    assert c.seen == [0, 1, 2, 3, 4]


def test_variable_latency_can_reorder() -> None:
    # with latency spread, some seed must deliver the burst out of order
    def order(seed: int) -> list[int]:
        c = Collector()
        sim = Simulator({"s": Burst(5), "c": c}, seed=seed, network=NetworkModel(min_latency=1, max_latency=20))
        sim.run()
        return c.seen

    assert any(order(s) != [0, 1, 2, 3, 4] for s in range(30))
    assert all(sorted(order(s)) == [0, 1, 2, 3, 4] for s in range(30))  # nothing lost, just reordered


class TimeoutRetrier(BaseNode):
    """Sends a request; if no reply before the timer, retries (bounded). Counts attempts."""

    def __init__(self) -> None:
        self.attempts = 0
        self.acked = False

    def on_start(self, ctx: Context) -> None:
        self._try(ctx)

    def _try(self, ctx: Context) -> None:
        if self.acked or self.attempts >= 5:
            return
        self.attempts += 1
        ctx.send("b", "req")
        ctx.set_timer("retry", delay=3)

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "ack":
            self.acked = True

    def on_timer(self, ctx: Context, name: str) -> None:
        self._try(ctx)


class FlakyServer(BaseNode):
    """Ignores the first request, acks the rest -- so the client must time out and retry once."""

    def __init__(self) -> None:
        self.got = 0

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        self.got += 1
        if self.got >= 2:
            ctx.send(src, "ack")


def test_timers_fire_and_drive_a_retry() -> None:
    client = TimeoutRetrier()
    sim = Simulator({"a": client, "b": FlakyServer()}, seed=1)
    sim.run()
    assert client.acked
    assert client.attempts == 2  # first ignored, retry acked


def test_a_partition_drops_all_traffic_on_a_cut_link() -> None:
    a, b = Pinger(), Ponger()
    cut = FaultSchedule(partitions=(Partition(frozenset({("a", "b")}), start=0, end=100),))
    sim = Simulator({"a": a, "b": b}, seed=1, faults=cut)
    result = sim.run()
    assert b.pings == 0 and a.pongs == 0  # the ping never crosses the cut link
    assert result.dropped >= 1


def test_a_crashed_node_drops_inbound_then_recovers_on_restart() -> None:
    class Acker(BaseNode):
        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            ctx.send(src, "ack")

    client, server = TimeoutRetrier(), Acker()
    crash = FaultSchedule(crashes=(Crash(node="b", start=0, end=5),))
    sim = Simulator({"a": client, "b": server}, seed=1, faults=crash)
    sim.run()
    assert client.acked  # a retry after b restarts gets through
    assert client.attempts >= 2  # at least one request was lost while b was down
