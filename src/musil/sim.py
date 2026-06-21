"""Deterministic simulation: run real, event-driven node code under a controlled world.

The expensive distributed bugs hide in *timing* -- message loss, reordering, a timeout racing a reply,
a partition healing at the wrong moment. This runs your actual node logic against a virtual network
and clock where all of that is controlled and seeded, so every run is **reproducible from its seed**
(a found bug replays exactly). It's the FoundationDB/TigerBeetle "deterministic simulation testing"
technique as a pure-Python library -- bug *finding*, not proof.

Model: nodes are event-driven actors (``on_start`` / ``on_message`` / ``on_timer``) that act through a
``Context`` (send a message, set a timer, read the virtual clock, draw seeded randomness). The
``Simulator`` owns a discrete-event queue ordered by (virtual time, sequence); the ``NetworkModel``
decides per-message loss / duplication / latency, so reordering and delay emerge from latency spread.
All randomness comes from one seeded RNG. ``musil.refine`` + invariants are the oracle (next slice:
``simulate``)."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Envelope:
    """A message in flight: a unique sequence number, source, destination, and payload."""

    seq: int
    src: str
    dst: str
    payload: object


@dataclass(frozen=True, slots=True)
class NetworkModel:
    """How the virtual network treats each message. Defaults are a reliable, in-order channel; set
    ``loss``/``duplicate`` (probabilities in [0, 1]) and a ``min_latency``/``max_latency`` spread
    (virtual-time units) to inject drops, duplicates, and reordering. All draws use the sim's seed."""

    loss: float = 0.0
    duplicate: float = 0.0
    min_latency: int = 1
    max_latency: int = 1


@dataclass(frozen=True, slots=True)
class _Deliver:
    env: Envelope


@dataclass(frozen=True, slots=True)
class _Timer:
    node: str
    name: str


type _Event = _Deliver | _Timer


@dataclass(frozen=True, slots=True)
class RunResult:
    """Outcome of a run. ``reason`` is ``"quiescent"`` (queue drained), ``"until"`` (goal predicate
    met), or ``"max-steps"`` (step cap hit)."""

    steps: int
    time: int
    delivered: int
    dropped: int
    reason: str


class Context:
    """A node's handle on the world, passed to every handler. Lets the node send messages, arm/cancel
    timers, read the virtual clock (``now``), and draw seeded randomness -- never use real time or the
    global ``random`` module in a node, or runs stop being reproducible."""

    __slots__ = ("_node", "_sim")

    def __init__(self, sim: Simulator, node: str) -> None:
        self._sim = sim
        self._node = node

    @property
    def node(self) -> str:
        return self._node

    @property
    def now(self) -> int:
        return self._sim.now

    def send(self, dst: str, payload: object) -> None:
        self._sim.inject(self._node, dst, payload)

    def set_timer(self, name: str, delay: int = 1) -> None:
        """Arm (or re-arm) a timer; it fires ``delay`` virtual-time units from now via ``on_timer``.
        Re-arming a live timer of the same name replaces it."""
        self._sim.schedule_timer(self._node, name, delay)

    def cancel_timer(self, name: str) -> None:
        self._sim.cancel_timer(self._node, name)

    def random(self) -> float:
        return self._sim.random()

    def randint(self, a: int, b: int) -> int:
        return self._sim.randint(a, b)


class Node(Protocol):
    """What the simulator needs from a node: three event handlers. Subclass ``BaseNode`` and override
    only the ones you need."""

    def on_start(self, ctx: Context) -> None: ...
    def on_message(self, ctx: Context, src: str, payload: object) -> None: ...
    def on_timer(self, ctx: Context, name: str) -> None: ...


class BaseNode:
    """A node with no-op handlers; override what you need. Keep all mutable state on the instance."""

    def on_start(self, ctx: Context) -> None:
        pass

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        pass

    def on_timer(self, ctx: Context, name: str) -> None:
        pass


class Simulator:
    """Runs a fixed set of named nodes under a virtual clock and network. Construct with the node
    map, a ``seed``, and an optional ``NetworkModel``; call ``run``. Determinism: identical
    (nodes, seed, network) always produce the identical run."""

    __slots__ = (
        "_active_timers", "_counter", "_ctxs", "_delivered", "_dropped", "_events",
        "_net", "_nodes", "_now", "_queue", "_rng",
    )

    def __init__(
        self,
        nodes: Mapping[str, Node],
        *,
        seed: int = 0,
        network: NetworkModel | None = None,
    ) -> None:
        self._nodes: dict[str, Node] = dict(nodes)
        self._net = network if network is not None else NetworkModel()
        self._rng = Random(seed)
        self._now: int = 0
        self._counter: int = 0
        self._delivered: int = 0
        self._dropped: int = 0
        self._queue: list[tuple[int, int]] = []  # (due_time, seq) min-heap
        self._events: dict[int, _Event] = {}
        self._active_timers: dict[tuple[str, str], int] = {}
        self._ctxs: dict[str, Context] = {name: Context(self, name) for name in self._nodes}

    @property
    def now(self) -> int:
        return self._now

    def _schedule(self, due: int, event: _Event) -> int:
        self._counter += 1
        seq = self._counter
        self._events[seq] = event
        heapq.heappush(self._queue, (due, seq))
        return seq

    def random(self) -> float:
        """A seeded random float in [0, 1) -- the only randomness nodes may use (keeps runs reproducible)."""
        return self._rng.random()

    def randint(self, a: int, b: int) -> int:
        """A seeded random integer in [a, b]."""
        return self._rng.randint(a, b)

    def inject(self, src: str, dst: str, payload: object) -> None:
        """Send a message (from a node's ``ctx.send``, or externally to kick the system). Subject to
        the network model: it may be dropped, duplicated, or delayed."""
        if dst not in self._nodes:
            raise ValueError(f"send to unknown node {dst!r} (known: {sorted(self._nodes)})")
        net = self._net
        if net.loss > 0.0 and self._rng.random() < net.loss:
            self._dropped += 1
            return
        latency = self._rng.randint(net.min_latency, net.max_latency)
        env = Envelope(seq=self._counter + 1, src=src, dst=dst, payload=payload)
        self._schedule(self._now + latency, _Deliver(env))
        if net.duplicate > 0.0 and self._rng.random() < net.duplicate:
            dup_latency = self._rng.randint(net.min_latency, net.max_latency)
            self._schedule(self._now + dup_latency, _Deliver(env))

    def schedule_timer(self, node: str, name: str, delay: int) -> None:
        """Arm a timer for ``node`` that fires ``delay`` units from now (re-arming replaces it)."""
        seq = self._schedule(self._now + max(delay, 1), _Timer(node, name))
        self._active_timers[(node, name)] = seq

    def cancel_timer(self, node: str, name: str) -> None:
        self._active_timers.pop((node, name), None)

    def run(
        self,
        *,
        max_steps: int = 10_000,
        until: Callable[[Simulator], bool] | None = None,
        on_step: Callable[[Simulator], None] | None = None,
    ) -> RunResult:
        """Drive the system to quiescence (queue empty), until ``until(sim)`` is true, or until
        ``max_steps`` events have fired. ``on_step(sim)`` runs after each fired event -- the hook the
        oracle uses to snapshot and check the world."""
        for name in sorted(self._nodes):
            self._nodes[name].on_start(self._ctxs[name])
        if until is not None and until(self):
            return RunResult(0, self._now, self._delivered, self._dropped, "until")

        steps = 0
        reason = "quiescent"
        while self._queue:
            if steps >= max_steps:
                reason = "max-steps"
                break
            due, seq = heapq.heappop(self._queue)
            event = self._events.pop(seq)
            if isinstance(event, _Timer):
                if self._active_timers.get((event.node, event.name)) != seq:
                    continue  # cancelled or superseded by a re-arm
                self._active_timers.pop((event.node, event.name), None)
                self._now = due
                self._nodes[event.node].on_timer(self._ctxs[event.node], event.name)
            else:
                self._now = due
                self._delivered += 1
                env = event.env
                self._nodes[env.dst].on_message(self._ctxs[env.dst], env.src, env.payload)
            steps += 1
            if on_step is not None:
                on_step(self)
            if until is not None and until(self):
                reason = "until"
                break

        return RunResult(steps, self._now, self._delivered, self._dropped, reason)
