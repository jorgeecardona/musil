"""AdversarialNode and NetworkModel.mutate: Byzantine fault injection in simulation."""

from __future__ import annotations

from collections.abc import Mapping

from musil.sim import AdversarialNode, BaseNode, Context, NetworkModel, Node, Simulator, simulate

# --- AdversarialNode: basic behavior routing ---

class Requester(BaseNode):
    """Sends a request and records the response."""

    def __init__(self) -> None:
        self.response: object = None
        self.received: int = 0

    def on_start(self, ctx: Context) -> None:
        ctx.send("service", "get")

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        self.response = payload
        self.received += 1


def test_adversarial_node_sends_wrong_answer() -> None:
    requester = Requester()

    wrong_answer_service = AdversarialNode(
        behaviors=[
            (
                lambda src, payload: payload == "get",
                lambda ctx, src, payload: ctx.send(src, "WRONG"),
            ),
        ]
    )

    sim = Simulator({"client": requester, "service": wrong_answer_service})
    sim.run()

    assert requester.response == "WRONG"
    assert requester.received == 1


def test_adversarial_node_ignores_unknown_messages() -> None:
    requester = Requester()

    # no guard matches "get" → message is silently dropped
    silent_service = AdversarialNode(
        behaviors=[
            (lambda src, payload: payload == "something_else", lambda ctx, src, payload: ctx.send(src, "ok")),
        ]
    )

    sim = Simulator({"client": requester, "service": silent_service})
    sim.run()

    assert requester.received == 0
    assert requester.response is None


def test_adversarial_node_first_matching_guard_fires() -> None:
    """When multiple guards match, only the first fires."""
    requester = Requester()

    service = AdversarialNode(
        behaviors=[
            (lambda src, payload: payload == "get", lambda ctx, src, payload: ctx.send(src, "first")),
            (lambda src, payload: payload == "get", lambda ctx, src, payload: ctx.send(src, "second")),
        ]
    )

    sim = Simulator({"client": requester, "service": service})
    sim.run()

    assert requester.response == "first"
    assert requester.received == 1


def test_adversarial_node_empty_behaviors_drops_everything() -> None:
    requester = Requester()
    silent = AdversarialNode(behaviors=[])
    sim = Simulator({"client": requester, "service": silent})
    sim.run()
    assert requester.received == 0


# --- NetworkModel.mutate: payload corruption ---

def test_mutate_replaces_payload() -> None:
    requester = Requester()

    class Responder(BaseNode):
        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            ctx.send(src, "correct")

    def corrupt(_src: str, _dst: str, payload: object) -> object | None:
        if payload == "correct":
            return "corrupted"
        return payload

    net = NetworkModel(mutate=corrupt)
    sim = Simulator({"client": requester, "service": Responder()}, network=net)
    sim.run()

    assert requester.response == "corrupted"


def test_mutate_returning_none_drops_message() -> None:
    requester = Requester()

    class Responder(BaseNode):
        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            ctx.send(src, "reply")

    def drop_replies(_src: str, _dst: str, payload: object) -> object | None:
        if payload == "reply":
            return None  # drop all replies
        return payload

    net = NetworkModel(mutate=drop_replies)
    sim = Simulator({"client": requester, "service": Responder()}, network=net)
    result = sim.run()

    assert requester.received == 0
    assert result.dropped == 1


def test_mutate_passes_through_unmatched_messages() -> None:
    requester = Requester()

    class Responder(BaseNode):
        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            ctx.send(src, "ok")

    def noop_mutate(_src: str, _dst: str, payload: object) -> object | None:
        return payload  # pass through unchanged

    net = NetworkModel(mutate=noop_mutate)
    sim = Simulator({"client": requester, "service": Responder()}, network=net)
    sim.run()

    assert requester.response == "ok"


# --- Determinism: same seed → same adversarial sequence ---

def test_adversarial_node_is_deterministic_across_seeds() -> None:
    """AdversarialNode behaviors are pure functions; runs are deterministic by construction."""

    class Counter(BaseNode):
        def __init__(self) -> None:
            self.count = 0

        def on_start(self, ctx: Context) -> None:
            ctx.send("adv", "ping")

        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            if payload == "pong":
                self.count += 1

    def make() -> Mapping[str, Node]:
        return {
            "client": Counter(),
            "adv": AdversarialNode(
                behaviors=[
                    (lambda src, payload: payload == "ping", lambda ctx, src, payload: ctx.send(src, "pong")),
                ]
            ),
        }

    def snapshot(nodes: Mapping[str, Node]) -> int:
        n = nodes["client"]
        assert isinstance(n, Counter)
        return n.count

    report1 = simulate(make, seeds=[0, 1, 2], snapshot=snapshot, goal=lambda c: c >= 1)
    report2 = simulate(make, seeds=[0, 1, 2], snapshot=snapshot, goal=lambda c: c >= 1)

    assert report1.ok == report2.ok


# --- mutate applied in correct position (after loss, before delivery) ---

def test_mutate_not_applied_to_dropped_messages() -> None:
    """Mutate should not fire for messages already dropped by loss=1.0."""
    mutate_calls: list[tuple[str, str, object]] = []

    def recording_mutate(src: str, dst: str, payload: object) -> object | None:
        mutate_calls.append((src, dst, payload))
        return payload

    requester = Requester()

    class Responder(BaseNode):
        def on_message(self, ctx: Context, src: str, payload: object) -> None:
            ctx.send(src, "reply")

    net = NetworkModel(loss=1.0, mutate=recording_mutate)
    sim = Simulator({"client": requester, "service": Responder()}, network=net)
    sim.run()

    # every message lost before mutate fires → mutate never called
    assert len(mutate_calls) == 0
