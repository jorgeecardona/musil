"""The generic message-channel kit: reliable / lossy / reordering / duplicating semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, channel_actions, explore, send

MSGS = ("a", "b")


@dataclass(frozen=True)
class Wire:
    inflight: frozenset[str] = frozenset()
    sent: frozenset[str] = frozenset()
    received: tuple[str, ...] = ()  # ordered log of deliveries


_get = lambda s: s.inflight  # noqa: E731
_put = lambda s, nf: replace(s, inflight=nf)  # noqa: E731
# cap at 2 deliveries per message so a duplicating channel's state space stays bounded
_deliver = lambda s, m: s if s.received.count(m) >= 2 else replace(s, received=(*s.received, m))  # noqa: E731
_inject = send(_get, _put)


def _model(*, lossy: bool = False, duplicating: bool = False) -> Model[Wire]:
    sends = [
        Action(f"send:{m}", lambda s, _m=m: _m not in s.sent, lambda s, _m=m: _inject(replace(s, sent=s.sent | {_m}), _m))
        for m in MSGS
    ]
    return Model(
        init=Wire(),
        actions=[*sends, *channel_actions(messages=MSGS, get=_get, put=_put, deliver=_deliver, lossy=lossy, duplicating=duplicating)],
        terminal=lambda s: not s.inflight and s.sent == frozenset(MSGS),
    )


def _reachable(model: Model[Wire]) -> list[Wire]:
    return list(explore(model).states)


def test_reliable_channel_has_no_drop_and_can_deliver_everything() -> None:
    model = _model()
    assert all("drop" not in a.name for a in model.actions)
    states = _reachable(model)
    # a state where both messages have been received (nothing is lost in a reliable channel)
    assert any(set(s.received) == {"a", "b"} for s in states)


def test_lossy_channel_can_drop_a_message_so_it_never_arrives() -> None:
    model = _model(lossy=True)
    assert any("drop" in a.name for a in model.actions)
    states = _reachable(model)
    # a terminal-ish state where 'a' was sent but never received (dropped)
    assert any(s.sent == {"a", "b"} and not s.inflight and "a" not in s.received for s in states)


def test_channel_delivers_out_of_order_reordering() -> None:
    states = _reachable(_model())
    assert any(s.received == ("a", "b") for s in states)
    assert any(s.received == ("b", "a") for s in states)  # the other order is reachable too


def test_duplicating_channel_can_deliver_twice() -> None:
    states = _reachable(_model(duplicating=True))
    assert any(s.received.count("a") == 2 for s in states)
