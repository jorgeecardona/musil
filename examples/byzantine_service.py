"""Deterministic simulation testing with Byzantine fault injection.

A Byzantine node doesn't just fail silently — it actively sends wrong answers (Castro & Liskov,
OSDI 1999). This example uses ``AdversarialNode`` and ``NetworkModel(mutate=...)`` to inject two
kinds of Byzantine behavior:

1. **Wrong-answer injection** (``AdversarialNode``): an external service that sometimes responds
   with an incorrect value. Without response validation the client accepts it; with validation it
   detects and rejects bad answers.

2. **Payload mutation** (``NetworkModel.mutate``): the network corrupts messages in transit.
   The receiving node either crashes on unexpected types or handles corruption gracefully.

Both failure modes are seeded and deterministic — a found bug replays exactly from its seed.

  python examples/byzantine_service.py
"""

from __future__ import annotations

from collections.abc import Mapping

from musil.sim import AdversarialNode, BaseNode, Context, NetworkModel, Node, simulate

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

_EXPECTED_VALUE = 42
_BAD_VALUE = -1


# ---------------------------------------------------------------------------
# Client node
# ---------------------------------------------------------------------------

class Client(BaseNode):
    """Asks an external service for a value; validates the response."""

    def __init__(self, *, validate: bool) -> None:
        self._validate = validate
        self.accepted: int | None = None
        self.rejected: int = 0

    def on_start(self, ctx: Context) -> None:
        ctx.send("service", "query")

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if not isinstance(payload, int):
            # payload was corrupted (not an int) → drop silently
            return
        if self._validate and payload != _EXPECTED_VALUE:
            self.rejected += 1
            return
        self.accepted = payload


def _snapshot(nodes: Mapping[str, Node]) -> dict[str, object]:
    c = nodes["client"]
    assert isinstance(c, Client)
    return {"accepted": c.accepted, "rejected": c.rejected}


# ---------------------------------------------------------------------------
# Scenario 1: AdversarialNode — wrong-answer injection
# ---------------------------------------------------------------------------

def _byzantine_service() -> AdversarialNode:
    """External service: sometimes returns a wrong answer instead of _EXPECTED_VALUE."""
    def always_wrong(src: str, payload: object) -> bool:
        return payload == "query"

    def send_wrong(ctx: Context, src: str, payload: object) -> None:
        ctx.send(src, _BAD_VALUE)  # deliberately wrong

    return AdversarialNode(behaviors=[(always_wrong, send_wrong)])


def _make_nodes(validate: bool) -> Mapping[str, Node]:
    return {"client": Client(validate=validate), "service": _byzantine_service()}


def run_wrong_answer_scenario() -> None:
    print("Scenario 1: Byzantine service sends wrong answer\n")

    # Without validation: the client accepts the wrong answer → goal fails (accepted != expected).
    no_validate = simulate(
        lambda: _make_nodes(validate=False),
        seeds=range(20),
        snapshot=_snapshot,
        goal=lambda w: w["accepted"] == _EXPECTED_VALUE,
        goal_name="accepted==expected",
    )
    print(f"  Without validation: {no_validate}")
    assert not no_validate.ok

    # With validation: the client rejects the wrong answer and accepted stays None.
    # goal is "no bad value accepted" — i.e., accepted is None (the client refused everything).
    with_validate = simulate(
        lambda: _make_nodes(validate=True),
        seeds=range(20),
        snapshot=_snapshot,
        goal=lambda w: w["accepted"] != _BAD_VALUE,  # bad value was never accepted
        goal_name="bad-value-rejected",
    )
    print(f"  With validation:    {with_validate}")
    assert with_validate.ok, str(with_validate)
    print()


# ---------------------------------------------------------------------------
# Scenario 2: NetworkModel.mutate — wire-level payload corruption
# ---------------------------------------------------------------------------

class StrictClient(BaseNode):
    """Sends a query; crashes if it receives anything that's not a plain int."""

    def __init__(self) -> None:
        self.received: object = None
        self.crashed = False

    def on_start(self, ctx: Context) -> None:
        ctx.send("service", "query")

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if not isinstance(payload, int):
            self.crashed = True
            return
        self.received = payload


class HonestService(BaseNode):
    """Returns the correct answer, always."""

    def on_message(self, ctx: Context, src: str, payload: object) -> None:
        if payload == "query":
            ctx.send(src, _EXPECTED_VALUE)


def _corrupt_int_to_string(_src: str, _dst: str, payload: object) -> object | None:
    """Wire-level corruption: if the payload is an int response, corrupt it to a string."""
    if isinstance(payload, int):
        return f"corrupted:{payload}"
    return payload


def _make_corrupted_nodes() -> Mapping[str, Node]:
    return {"client": StrictClient(), "service": HonestService()}


def _snapshot2(nodes: Mapping[str, Node]) -> dict[str, object]:
    c = nodes["client"]
    assert isinstance(c, StrictClient)
    return {"received": c.received, "crashed": c.crashed}


def run_payload_corruption_scenario() -> None:
    print("Scenario 2: NetworkModel.mutate — wire-level payload corruption\n")

    # Without mutation: honest service, strict client — all good.
    clean = simulate(
        _make_corrupted_nodes,
        seeds=range(10),
        snapshot=_snapshot2,
        invariants={"no-crash": lambda w: not w["crashed"]},
    )
    print(f"  Clean network (no mutation):      {clean}")
    assert clean.ok

    # With mutation: integer responses corrupted to strings → client crashes (invariant fires).
    corrupted = simulate(
        _make_corrupted_nodes,
        seeds=range(10),
        snapshot=_snapshot2,
        network=NetworkModel(mutate=_corrupt_int_to_string),
        invariants={"no-crash": lambda w: not w["crashed"]},
    )
    print(f"  Corrupted network (mutate=...):   {corrupted}")
    assert not corrupted.ok
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("Byzantine fault injection — AdversarialNode and NetworkModel.mutate\n")
    run_wrong_answer_scenario()
    run_payload_corruption_scenario()
    print("Byzantine testing: wrong answers and wire corruption both detectable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
