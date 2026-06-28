"""Generic message-channel modeling kit -- the "model the network explicitly" principle as a reusable
building block (methodology doc section 3).

A channel's in-flight messages are held as a frozenset somewhere in your model's state. This kit
builds the channel's actions over that state: deliver a message (apply it to the receiver), and --
depending on the channel's reliability -- drop it (loss) or keep it after delivery (duplication).
Because the in-flight set is unordered and ``deliver`` may fire for ANY in-flight message, reordering
is modelled for free; ``lossy`` adds message loss; ``duplicating`` allows redelivery. (A set dedups a
re-send of the same message -- which matches an idempotent re-push. FIFO/ordered channels would need
a sequence instead; the realistic network is unordered, which is what this models.)

Domain-free: messages are any hashable values the caller supplies. Use ``send`` inside a sender's
action to inject a message, and ``channel_actions`` to add the channel's own steps to the model."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable

from musil.core import Action

type Message = Hashable


def send[S: Hashable](
    get: Callable[[S], frozenset[Message]], put: Callable[[S, frozenset[Message]], S]
) -> Callable[[S, Message], S]:
    """Return a helper ``send(state, msg)`` that injects ``msg`` into the channel's in-flight set
    (idempotent: re-sending an in-flight message is a no-op, like an idempotent re-push)."""
    return lambda s, msg: put(s, get(s) | frozenset({msg}))


def fifo_send[S: Hashable](
    get: Callable[[S], tuple[Message, ...]], put: Callable[[S, tuple[Message, ...]], S]
) -> Callable[[S, Message], S]:
    """Return a helper ``send(state, msg)`` that appends ``msg`` to the tail of an ORDERED channel
    (a tuple, not a set). Unlike the unordered ``send``, this is not idempotent — each call enqueues
    another copy — so the caller must bound the queue (e.g. only send when it's empty, or guard on a
    capacity) to keep the model finite."""
    return lambda s, msg: put(s, (*get(s), msg))


def fifo_channel_actions[S: Hashable](
    *,
    get: Callable[[S], tuple[Message, ...]],
    put: Callable[[S, tuple[Message, ...]], S],
    deliver: Callable[[S, Message], S],
    lossy: bool = False,
    name: str = "ch",
) -> list[Action[S]]:
    """An **ordered (FIFO)** channel's steps over the caller's state, the order-preserving counterpart
    to ``channel_actions``. The in-flight messages are an ordered tuple (``get``/``put`` read/write
    it); only the **head** is deliverable, so messages arrive in send order — no reordering. ``lossy``
    adds a head-drop (loss). ``deliver(state, msg)`` applies the delivered head to the receiver; the
    head is then removed. Use for sequence-number protocols (alternating-bit, sliding-window) and any
    link whose correctness assumes order — where the unordered ``channel_actions`` would wrongly
    explore reorderings. (Bound the queue from the sender side; see ``fifo_send``.)"""
    actions: list[Action[S]] = [
        Action(
            name=f"{name}:deliver",
            enabled=lambda s: bool(get(s)),
            apply=lambda s: put(deliver(s, get(s)[0]), get(s)[1:]),  # deliver head, then drop it
        )
    ]
    if lossy:
        actions.append(
            Action(name=f"{name}:drop", enabled=lambda s: bool(get(s)),
                   apply=lambda s: put(s, get(s)[1:]))  # lose the head
        )
    return actions


def _deliver_action[S: Hashable](
    name: str,
    get: Callable[[S], frozenset[Message]],
    put: Callable[[S, frozenset[Message]], S],
    deliver: Callable[[S, Message], S],
    msg: Message,
    duplicating: bool,
) -> Action[S]:
    def apply(s: S) -> S:
        delivered = deliver(s, msg)  # let the caller apply the message to the receiver slice
        if duplicating:
            return delivered  # keep it in flight -> it can be delivered again
        return put(delivered, get(delivered) - frozenset({msg}))

    return Action(name=name, enabled=lambda s: msg in get(s), apply=apply)


def _drop_action[S: Hashable](
    name: str,
    get: Callable[[S], frozenset[Message]],
    put: Callable[[S, frozenset[Message]], S],
    msg: Message,
) -> Action[S]:
    return Action(
        name=name,
        enabled=lambda s: msg in get(s),
        apply=lambda s: put(s, get(s) - frozenset({msg})),
    )


def channel_actions[S: Hashable](
    *,
    messages: Iterable[Message],
    get: Callable[[S], frozenset[Message]],
    put: Callable[[S, frozenset[Message]], S],
    deliver: Callable[[S, Message], S],
    lossy: bool = False,
    duplicating: bool = False,
    name: str = "ch",
) -> list[Action[S]]:
    """The channel's steps over the caller's state. ``get``/``put`` read/write the in-flight set;
    ``deliver(state, msg)`` applies a delivered message to the receiver. ``messages`` is the (bounded)
    universe of possible messages. ``lossy`` adds drop steps; ``duplicating`` lets a message be
    delivered more than once. Delivery order is unconstrained (reordering)."""
    actions: list[Action[S]] = []
    for m in messages:
        actions.append(_deliver_action(f"{name}:deliver:{m!r}", get, put, deliver, m, duplicating))
        if lossy:
            actions.append(_drop_action(f"{name}:drop:{m!r}", get, put, m))
    return actions
