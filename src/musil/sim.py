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
A ``FaultSchedule`` layers on *sustained* faults -- network partitions and node crashes that hold for a
window then heal -- so ``simulate`` can check **liveness**: does the system converge once they lift?
All randomness comes from one seeded RNG. ``musil.refine`` + invariants are the oracle (next slice:
``simulate``)."""

from __future__ import annotations

import heapq
import time
from collections.abc import Callable, Hashable, Iterable, Mapping
from dataclasses import dataclass
from random import Random
from typing import Protocol

from musil.core import Model
from musil.refine import RefinementMonitor

__all__ = [
    "AdversarialNode",
    "BaseNode",
    "Context",
    "Crash",
    "Envelope",
    "FaultDrive",
    "FaultSchedule",
    "NetworkModel",
    "Node",
    "Partition",
    "RunResult",
    "SimFailure",
    "SimReport",
    "Simulator",
    "simulate",
]


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
    (virtual-time units) to inject drops, duplicates, and reordering. All draws use the sim's seed.

    ``mutate`` is a Byzantine fault hook: ``mutate(src, dst, payload) -> object | None``. The
    returned value replaces the payload before delivery; returning ``None`` drops the message.
    Applied after loss/duplicate decisions, so it targets messages that survive the network model.
    Models wire-level corruption, wrong-answer injection, or selective drops (Castro & Liskov, OSDI
    1999)."""

    loss: float = 0.0
    duplicate: float = 0.0
    min_latency: int = 1
    max_latency: int = 1
    mutate: Callable[[str, str, object], object | None] | None = None


@dataclass(frozen=True, slots=True)
class Partition:
    """A sustained network fault: every directed link in ``links`` (``(src, dst)`` pairs) drops ALL
    traffic while active -- the window ``[start, end)`` in virtual time -- then heals. Unlike
    ``NetworkModel.loss`` (independent per message, which a retrying sender papers over), a partition
    cuts the link wholesale, so the system can only recover once it lifts. This is what makes a real
    *liveness* test: does it converge after the partition heals?"""

    links: frozenset[tuple[str, str]]
    start: int
    end: int

    def cuts(self, src: str, dst: str, t: int) -> bool:
        return self.start <= t < self.end and (src, dst) in self.links


@dataclass(frozen=True, slots=True)
class Crash:
    """A sustained process fault: ``node`` is down over ``[start, end)`` -- inbound messages are
    dropped, its timers don't fire, it runs no handlers -- then restarts. ``lose_state=True`` is a cold
    restart (a fresh node instance that re-runs ``on_start``); the default is a warm resume that keeps
    the instance's state (it missed everything while down)."""

    node: str
    start: int
    end: int
    lose_state: bool = False

    def down(self, node: str, t: int) -> bool:
        return node == self.node and self.start <= t < self.end


@dataclass(frozen=True, slots=True)
class FaultDrive:
    """What :meth:`FaultSchedule.drive` did: how many fault windows it opened and closed, and the
    virtual time the last one healed (after which a live system must converge)."""

    applied: int
    healed: int
    heal_time: int


@dataclass(frozen=True, slots=True)
class FaultSchedule:
    """A fixed set of sustained faults for one run. ``heal_time()`` is when the last fault lifts (the
    world is clean again) -- the point after which a live system must converge to its goal. Build one
    explicitly, or per-seed via a ``Callable[[Random], FaultSchedule]`` so randomized schedules stay
    seed-reproducible."""

    partitions: tuple[Partition, ...] = ()
    crashes: tuple[Crash, ...] = ()

    def heal_time(self) -> int:
        return max([p.end for p in self.partitions] + [c.end for c in self.crashes], default=0)

    def drive(
        self,
        apply_fault: Callable[[Partition | Crash], object],
        heal_fault: Callable[[Partition | Crash], object],
        *,
        seconds_per_tick: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> FaultDrive:
        """Drive a REAL system through this schedule, firing a callback at each fault boundary in
        virtual-time order: ``apply_fault(fault)`` when a fault's window opens, ``heal_fault(fault)``
        when it closes. The fault is the ``Partition`` or ``Crash`` itself, so the caller dispatches on
        type -- a ``Crash`` to ``proc.kill()`` then a restart, a ``Partition`` to ``ip link down`` then
        up.

        This is the bridge the conformance story was missing: the SAME ``FaultSchedule`` that injects
        faults into a model run in the simulator now injects them into the running fleet, so "does the
        implementation refine the spec under the same faults?" is one schedule, asked twice. Pair it
        with :class:`musil.conformance.ConvergenceMonitor` to assert the fleet reconverges after
        ``heal_time``.

        Virtual ticks are paced to wall time by ``seconds_per_tick`` through ``sleep``; inject ``sleep``
        (e.g. a virtual clock's advance) to drive a simulated fleet or to test without waiting. At a
        shared instant, heals fire before applies (a link frees before another cuts)."""
        faults: tuple[Partition | Crash, ...] = (*self.partitions, *self.crashes)
        # (time, is_apply, fault); is_apply False (heal) sorts before True (apply) at the same instant.
        events = sorted(
            [(f.start, True, f) for f in faults] + [(f.end, False, f) for f in faults],
            key=lambda e: (e[0], e[1]),
        )
        now = 0
        applied = healed = 0
        for t, is_apply, fault in events:
            if t > now:
                sleep((t - now) * seconds_per_tick)
                now = t
            if is_apply:
                apply_fault(fault)
                applied += 1
            else:
                heal_fault(fault)
                healed += 1
        return FaultDrive(applied=applied, healed=healed, heal_time=self.heal_time())

    def link_cut(self, src: str, dst: str, t: int) -> bool:
        return any(p.cuts(src, dst, t) for p in self.partitions)

    def node_down(self, node: str, t: int) -> bool:
        return any(c.down(node, t) for c in self.crashes)

    def crash_ending_at(self, node: str, t: int) -> Crash | None:
        for c in self.crashes:
            if c.node == node and c.end == t:
                return c
        return None


@dataclass(frozen=True, slots=True)
class _Deliver:
    env: Envelope


@dataclass(frozen=True, slots=True)
class _Timer:
    node: str
    name: str


@dataclass(frozen=True, slots=True)
class _Restart:
    node: str


type _Event = _Deliver | _Timer | _Restart


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


class AdversarialNode(BaseNode):
    """A simulation node that injects adversarial behavior via a prioritized behavior list.

    Models an external component (a K8s node, an AWS service, a Byzantine peer) that sometimes
    misbehaves. Each behavior is a ``(guard, response)`` pair:

    - ``guard(src, payload) -> bool``  — returns True when this behavior should fire.
    - ``response(ctx, src, payload) -> None``  — the adversarial action: send wrong data,
      send nothing, send duplicate responses, violate the protocol.

    On each ``on_message``, behaviors are tried in order; the first matching guard fires and
    no further behaviors are tried. If no guard matches, the message is silently dropped —
    the default adversarial posture (an external service that ignores requests).

    All randomness in behavior callbacks must go through ``ctx.random()`` / ``ctx.randint()``
    so runs stay reproducible across seeds. This is the simulation counterpart of
    ``EnvironmentSpec``: same contract theory, different execution model.
    """

    def __init__(
        self,
        behaviors: list[
            tuple[
                Callable[[str, object], bool],  # guard(src, payload)
                Callable[[Context, str, object], None],  # response(ctx, src, payload)
            ]
        ],
    ) -> None:
        self._behaviors = behaviors

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        for guard, response in self._behaviors:
            if guard(src, payload):
                response(ctx, src, payload)
                return


class Simulator:
    """Runs a fixed set of named nodes under a virtual clock and network. Construct with the node
    map, a ``seed``, and an optional ``NetworkModel``; call ``run``. Determinism: identical
    (nodes, seed, network) always produce the identical run."""

    __slots__ = (
        "_active_timers",
        "_counter",
        "_ctxs",
        "_delivered",
        "_dropped",
        "_events",
        "_faults",
        "_net",
        "_nodes",
        "_now",
        "_queue",
        "_rebuild",
        "_rng",
        "_started",
    )

    def __init__(
        self,
        nodes: Mapping[str, Node],
        *,
        seed: int = 0,
        network: NetworkModel | None = None,
        faults: FaultSchedule | None = None,
        rebuild: Callable[[], Mapping[str, Node]] | None = None,
    ) -> None:
        self._nodes: dict[str, Node] = dict(nodes)
        self._net = network if network is not None else NetworkModel()
        self._faults = faults
        # how to build a fresh node for a cold restart (Crash.lose_state); the per-node fresh
        # instance is taken from a fresh full map, so the same factory simulate already uses works.
        self._rebuild = rebuild
        self._rng = Random(seed)
        self._now: int = 0
        self._counter: int = 0
        self._delivered: int = 0
        self._dropped: int = 0
        self._queue: list[tuple[int, int]] = []  # (due_time, seq) min-heap
        self._events: dict[int, _Event] = {}
        self._active_timers: dict[tuple[str, str], int] = {}
        self._started: set[str] = set()
        self._ctxs: dict[str, Context] = {name: Context(self, name) for name in self._nodes}

    @property
    def nodes(self) -> Mapping[str, Node]:
        """The live node map -- the authoritative instances, which a cold restart swaps. The oracle
        snapshots through this so it always reads post-restart state."""
        return self._nodes

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
        if self._faults is not None and self._faults.link_cut(src, dst, self._now):
            self._dropped += 1  # link partitioned right now -> the message never makes it on
            return
        net = self._net
        if net.loss > 0.0 and self._rng.random() < net.loss:
            self._dropped += 1
            return
        if net.mutate is not None:
            payload = net.mutate(src, dst, payload)
            if payload is None:
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
        after_start: Callable[[Simulator], None] | None = None,
    ) -> RunResult:
        """Drive the system to quiescence (queue empty), until ``until(sim)`` is true, or until
        ``max_steps`` events have fired. ``after_start(sim)`` runs once after every node's
        ``on_start`` (the initial world); ``on_step(sim)`` runs after each fired event -- the hooks
        the oracle uses to snapshot and check the world."""
        for name in sorted(self._nodes):
            if self._faults is not None and self._faults.node_down(name, 0):
                continue  # crashed at t=0 -> it boots when its window ends (its _Restart event)
            self._nodes[name].on_start(self._ctxs[name])
            self._started.add(name)
        if self._faults is not None:
            for crash in self._faults.crashes:
                # a restart event both reboots the node AND keeps the queue alive until heal, so a
                # run that would otherwise go quiescent mid-crash still waits for recovery.
                self._schedule(crash.end, _Restart(crash.node))
        if after_start is not None:
            after_start(self)
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
                if self._faults is not None and self._faults.node_down(event.node, due):
                    continue  # node is down -> its timer is lost
                self._now = due
                self._nodes[event.node].on_timer(self._ctxs[event.node], event.name)
            elif isinstance(event, _Restart):
                self._now = due
                self._restart(event.node, due)
            else:
                env = event.env
                if self._faults is not None and self._faults.node_down(env.dst, due):
                    self._dropped += 1
                    continue  # destination is down -> message dropped on arrival
                self._now = due
                self._delivered += 1
                self._nodes[env.dst].on_message(self._ctxs[env.dst], env.src, env.payload)
            steps += 1
            if on_step is not None:
                on_step(self)
            if until is not None and until(self):
                reason = "until"
                break

        return RunResult(steps, self._now, self._delivered, self._dropped, reason)

    def _restart(self, node: str, t: int) -> None:
        """Bring ``node`` back up at the end of its crash window. A cold restart (``lose_state``) swaps
        in a fresh instance from the factory and re-runs ``on_start``; a warm one resumes the existing
        instance (and runs ``on_start`` only if the node was down from t=0 and never booted)."""
        crash = self._faults.crash_ending_at(node, t) if self._faults is not None else None
        if crash is not None and crash.lose_state and self._rebuild is not None:
            self._nodes[node] = self._rebuild()[node]
            self._started.discard(node)
        if node not in self._started:
            self._nodes[node].on_start(self._ctxs[node])
            self._started.add(node)


@dataclass(frozen=True, slots=True)
class SimFailure[W]:
    """A reproducible failure from ``simulate``. ``kind`` is ``"invariant"``, ``"refinement"``,
    ``"goal"`` (settled-but-goal-false with no faults), or ``"liveness"`` (under a ``FaultSchedule``,
    the system did not converge to the goal after the faults healed). ``detail`` names the broken
    invariant / refinement violation / goal. ``world`` is the offending snapshot and ``history`` the
    snapshots leading to it (a trace). Re-run with ``seeds=[seed]`` to reproduce exactly."""

    seed: int
    kind: str
    detail: str
    step: int
    world: W
    history: tuple[W, ...]

    def __str__(self) -> str:
        return (
            f"{self.kind.upper()} on seed {self.seed} at step {self.step}: {self.detail}\n"
            f"  world: {self.world}\n"
            f"  reproduce with seeds=[{self.seed}]"
        )


@dataclass(frozen=True, slots=True)
class SimReport[W]:
    ok: bool
    runs: int
    failure: SimFailure[W] | None = None

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return f"OK -- {self.runs} simulated runs, no failures"
        assert self.failure is not None
        return f"{self.failure}\n({self.runs} runs before the failing seed)"


class _OracleStop(Exception):
    """Internal: abort a run the instant the oracle finds a failure."""


class _Oracle[W, S: Hashable]:
    """Per-run checker fed to ``Simulator.run`` as the after-start / per-step hook: snapshots the
    world, checks invariants, and (if present) advances the refinement monitor; stashes the first
    failure and raises ``_OracleStop`` to abort the run."""

    __slots__ = (
        "_converge_within",
        "_goal",
        "_goal_name",
        "_heal_time",
        "_invariants",
        "_monitor",
        "_post_heal",
        "_seed",
        "_sim",
        "_snapshot",
        "failure",
        "history",
    )

    def __init__(
        self,
        seed: int,
        sim: Simulator,
        snapshot: Callable[[Mapping[str, Node]], W],
        invariants: Mapping[str, Callable[[W], bool]],
        monitor: RefinementMonitor[W, S] | None,
        *,
        goal: Callable[[W], bool] | None = None,
        goal_name: str = "goal",
        heal_time: int = 0,
        converge_within: int | None = None,
    ) -> None:
        self._seed = seed
        self._sim = (
            sim  # snapshot through the live sim so a cold restart's swapped instance is seen
        )
        self._snapshot = snapshot
        self._invariants = invariants
        self._monitor = monitor
        self._goal = goal
        self._goal_name = goal_name
        self._heal_time = heal_time
        self._converge_within = converge_within
        self._post_heal = 0
        self.history: list[W] = []
        self.failure: SimFailure[W] | None = None

    def __call__(self, _sim: Simulator) -> None:
        world = self._snapshot(self._sim.nodes)
        self.history.append(world)
        step = len(self.history) - 1
        for name, predicate in self._invariants.items():
            if not predicate(world):
                self.failure = SimFailure(
                    self._seed, "invariant", name, step, world, tuple(self.history)
                )
                raise _OracleStop
        if self._monitor is not None:
            violation = self._monitor.observe(world)
            if violation is not None:
                self.failure = SimFailure(
                    self._seed, "refinement", str(violation), step, world, tuple(self.history)
                )
                raise _OracleStop
        # liveness bound: once faults have healed, the goal must be reached within converge_within
        # steps -- catches livelock (busy but never converging) before quiescence/max_steps.
        if (
            self._goal is not None
            and self._converge_within is not None
            and self._sim.now >= self._heal_time
            and not self._goal(world)
        ):
            self._post_heal += 1
            if self._post_heal > self._converge_within:
                self.failure = SimFailure(
                    self._seed, "liveness", self._goal_name, step, world, tuple(self.history)
                )
                raise _OracleStop


def simulate[W, S: Hashable](
    factory: Callable[[], Mapping[str, Node]],
    *,
    seeds: Iterable[int],
    snapshot: Callable[[Mapping[str, Node]], W],
    network: NetworkModel | None = None,
    faults: FaultSchedule | Callable[[Random], FaultSchedule] | None = None,
    invariants: Mapping[str, Callable[[W], bool]] | None = None,
    model: Model[S] | None = None,
    abstraction: Callable[[W], S] | None = None,
    goal: Callable[[W], bool] | None = None,
    goal_name: str = "goal",
    converge_within: int | None = None,
    max_steps: int = 10_000,
    require_init: bool = True,
) -> SimReport[W]:
    """Deterministic simulation testing of the real nodes. Runs the system once per seed under
    ``network`` (independent per-message faults) and an optional ``faults`` schedule (sustained,
    heal-able partitions / crashes -- a ``FaultSchedule`` or a per-seed ``Random -> FaultSchedule``).
    After every step it checks each invariant and (if a ``model`` + ``abstraction`` are given) that the
    run refines the model -- safety holds *during* the chaos too. If a ``goal`` is given, the settled
    final world must satisfy it: with a non-trivial ``faults`` schedule this is the **liveness** check
    (did the system converge once the faults healed? -> ``kind="liveness"``); with no faults it is the
    plain convergence check (``kind="goal"``). ``converge_within`` (steps after the schedule's
    ``heal_time``) catches livelock early. Returns at the FIRST failing seed -- a reproducible repro
    (``report.failure.seed``). ``factory`` builds a fresh node map per run (also reused to cold-restart
    a crashed node); ``snapshot`` maps the live nodes to an immutable world value used by the oracle."""
    if model is not None and abstraction is None:
        raise ValueError(
            "model given without abstraction: pass abstraction=... to map worlds to model states"
        )
    invs: Mapping[str, Callable[[W], bool]] = invariants if invariants is not None else {}
    runs = 0
    for seed in seeds:
        runs += 1
        schedule = faults(Random(seed)) if callable(faults) else faults
        heal_time = schedule.heal_time() if schedule is not None else 0
        nodes = factory()
        sim = Simulator(nodes, seed=seed, network=network, faults=schedule, rebuild=factory)
        monitor: RefinementMonitor[W, S] | None = (
            RefinementMonitor(model, abstraction, require_init=require_init)
            if model is not None and abstraction is not None
            else None
        )
        oracle = _Oracle(
            seed,
            sim,
            snapshot,
            invs,
            monitor,
            goal=goal,
            goal_name=goal_name,
            heal_time=heal_time,
            converge_within=converge_within,
        )
        try:
            sim.run(max_steps=max_steps, after_start=oracle, on_step=oracle)
        except _OracleStop:
            return SimReport(ok=False, runs=runs, failure=oracle.failure)
        if goal is not None:
            final = oracle.history[-1] if oracle.history else snapshot(sim.nodes)
            if not goal(final):
                kind = "liveness" if heal_time > 0 else "goal"
                step = len(oracle.history) - 1
                return SimReport(
                    ok=False,
                    runs=runs,
                    failure=SimFailure(seed, kind, goal_name, step, final, tuple(oracle.history)),
                )
    return SimReport(ok=True, runs=runs)
