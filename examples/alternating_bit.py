"""Alternating Bit Protocol -- reliable, ordered delivery over a lossy channel, and the assumption
that makes it work.

The oldest data-link protocol that actually works, and the canonical reason a one-bit sequence number
exists. The sender tags each frame with a bit and retransmits it until it sees that bit echoed in an
ack; then it flips the bit and moves on. The receiver delivers a frame only when its bit matches the
bit it expects, and echoes the frame's bit either way. That single bit lets the receiver tell a
*fresh* message from a *retransmission* -- the difference between correct delivery and silently
handing the same byte up twice.

What this example actually demonstrates -- including a finding about musil itself:

  1. ABP NEEDS A *FIFO* CHANNEL. Point musil's channel kit (which models an **unordered** network --
     reordering for free) at ABP and `check` proves it UNSAFE: a two-generations-old frame survives in
     the network until the one-bit counter wraps, then is wrongly accepted. This is a true property of
     ABP -- it assumes order-preserving links -- and it surfaces a real gap in the kit: there is no
     ordered/FIFO channel mode. (See the note at the bottom -- this is a concrete improvement for musil.)

  2. WHY THE BIT EXISTS (safety). On a FIFO-but-duplicating link, a no-bit receiver delivers a
     duplicated frame twice. `check` returns the shortest trace to the bad state.

  3. THE BIT FIXES IT (safety). Real ABP on the FIFO link never delivers out of order or twice.

  4. WEAK FAIRNESS IS NOT ENOUGH (liveness). "Every message is eventually delivered" is FALSE under
     weak fairness (a lossy link may drop forever) and TRUE under STRONG fairness -- exactly the
     distinction the README points at: strong fairness is "what you need for delivery over a lossy
     channel." ABP is the minimal system that proves it.

Run me:  python examples/alternating_bit.py
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, replace
from typing import cast

from musil import Action, Model, channel_actions, check, check_liveness, send

# Number of application messages to push end to end. 3 is enough to wrap the one-bit counter
# (idx 0 and idx 2 both carry bit 0) -- which is precisely what breaks ABP on a reordering channel.
N = 3


# ====================================================================================================
# Part 1 -- ABP on musil's channel kit (an UNORDERED network). musil proves it needs FIFO.
# ====================================================================================================
#
# State as counts, not payloads: `r_idx` = messages the receiver has delivered, `s_idx` = messages the
# sender has had acked. The sender's bit is `s_idx % 2`, the receiver's expected bit is `r_idx % 2` --
# both derived, never stored, so they cannot drift. Channels are frozensets of in-flight frames/acks:
# unordered (reordering modelled for free) and dedup'd (a retransmission of an in-flight frame is a
# no-op, like a real resend).


@dataclass(frozen=True)
class Net:
    s_idx: int = 0
    r_idx: int = 0
    bad: bool = False  # set if the receiver ever delivers a frame out of order
    # The kit types every message as the broad `Hashable`, so the in-flight sets are typed that way
    # too; the frames are really (bit, idx) tuples and acks are bits, recovered on use.
    data: frozenset[Hashable] = frozenset()  # in-flight (bit, idx) frames
    acks: frozenset[Hashable] = frozenset()  # in-flight ack bits


def _get_data(s: Net) -> frozenset[Hashable]:
    return s.data


def _put_data(s: Net, fs: frozenset[Hashable]) -> Net:
    return replace(s, data=fs)


def _get_acks(s: Net) -> frozenset[Hashable]:
    return s.acks


def _put_acks(s: Net, fs: frozenset[Hashable]) -> Net:
    return replace(s, acks=fs)


_send_data = send(_get_data, _put_data)  # _send_data(state, frame) -> state with frame in flight
_send_ack = send(_get_acks, _put_acks)  # _send_ack(state, bit)     -> state with ack in flight


def _deliver_frame(s: Net, frame: Hashable) -> Net:
    """Receiver gets a frame. Deliver only if its bit matches the expected bit (a fresh message); a
    mismatched bit is a duplicate of something already delivered. Echo the frame's bit either way."""
    bit, idx = cast("tuple[int, int]", frame)
    if bit == s.r_idx % 2:
        s = replace(s, r_idx=s.r_idx + 1, bad=s.bad or idx != s.r_idx)
    return _send_ack(s, bit)


def _deliver_ack(s: Net, bit: Hashable) -> Net:
    """Sender gets an ack. If it carries the current bit, the current frame got through -> advance."""
    if bit == s.s_idx % 2 and s.s_idx < N:
        return replace(s, s_idx=s.s_idx + 1)
    return s


def build_unordered() -> Model[Net]:
    """ABP over musil's channel kit -- an unordered, lossy network. This is the WRONG channel for ABP."""
    send_frame = Action(
        "sender:send",
        enabled=lambda s: s.s_idx < N,
        apply=lambda s: _send_data(s, (s.s_idx % 2, s.s_idx)),
    )
    data_chan = channel_actions(
        messages=[(i % 2, i) for i in range(N)],
        get=_get_data, put=_put_data, deliver=_deliver_frame, lossy=True, name="data",
    )
    ack_chan = channel_actions(
        messages=[0, 1], get=_get_acks, put=_put_acks, deliver=_deliver_ack, lossy=True, name="ack",
    )
    return Model(
        init=Net(),
        actions=[send_frame, *data_chan, *ack_chan],
        invariants={"in-order": lambda s: not s.bad, "no-over-delivery": lambda s: s.r_idx <= N},
        terminal=lambda s: s.s_idx == N and s.r_idx == N,
    )


# ====================================================================================================
# Part 2 -- ABP on a hand-rolled single-slot FIFO channel. This is the channel ABP assumes.
# ====================================================================================================
#
# musil's kit has no ordered channel, so we model one directly: each direction is a single slot
# (capacity 1) holding at most one in-flight frame/ack. Capacity 1 makes order trivial and, crucially,
# stops a two-generations-old frame from coexisting with a new one -- the exact thing that wrecked the
# unordered version. `lossy` drops the slot; `duplicating` re-delivers it without clearing.


@dataclass(frozen=True)
class Slot:
    s_idx: int = 0
    r_idx: int = 0
    bad: bool = False
    data: tuple[int, int] | None = None  # the single in-flight frame, or empty
    ack: int | None = None  # the single in-flight ack bit, or empty


def _fifo_deliver_data(s: Slot, *, use_bit: bool, duplicating: bool) -> Slot:
    assert s.data is not None
    bit, idx = s.data
    accept = (bit == s.r_idx % 2) if use_bit else True  # no-bit receiver accepts everything
    if accept:
        s = replace(s, r_idx=s.r_idx + 1, bad=s.bad or idx != s.r_idx)
    s = replace(s, ack=bit)  # echo the received bit
    return s if duplicating else replace(s, data=None)  # clear the slot unless the link duplicates


def _fifo_deliver_ack(s: Slot) -> Slot:
    assert s.ack is not None
    if s.ack == s.s_idx % 2 and s.s_idx < N:
        s = replace(s, s_idx=s.s_idx + 1)
    return replace(s, ack=None)


def build_fifo(*, use_bit: bool, duplicating: bool = False) -> Model[Slot]:
    """ABP over a single-slot FIFO link. `use_bit=False` strips the sequence bit (point 2);
    `duplicating=True` lets the link re-deliver a frame (needed to expose the no-bit bug)."""
    send_frame: Action[Slot] = Action(  # retransmit: overwrite the slot with the current frame
        "sender:send",
        enabled=lambda s: s.s_idx < N,
        apply=lambda s: replace(s, data=(s.s_idx % 2, s.s_idx)),
    )
    data: list[Action[Slot]] = [
        Action("data:deliver", lambda s: s.data is not None,
               lambda s: _fifo_deliver_data(s, use_bit=use_bit, duplicating=duplicating)),
        Action("data:drop", lambda s: s.data is not None, lambda s: replace(s, data=None)),
    ]
    ack: list[Action[Slot]] = [
        Action("ack:deliver", lambda s: s.ack is not None, _fifo_deliver_ack),
        Action("ack:drop", lambda s: s.ack is not None, lambda s: replace(s, ack=None)),
    ]
    return Model(
        init=Slot(),
        actions=[send_frame, *data, *ack],
        invariants={"in-order": lambda s: not s.bad, "no-over-delivery": lambda s: s.r_idx <= N},
        terminal=lambda s: s.s_idx == N and s.r_idx == N,
    )


# ====================================================================================================
# Driver.
# ====================================================================================================


def _print_trace(result: object) -> None:
    print("  " + str(result).replace("\n", "\n  "))


def main() -> int:
    print("=== 1. ABP on musil's UNORDERED channel kit -- safety ===")
    un = check(build_unordered())
    if un.ok:
        print("  clean (unexpected!)")
    else:
        print(f"  UNSAFE -- invariant '{un.invariant}' violated. ABP needs FIFO; the kit is unordered:")
        _print_trace(un)

    print("\n=== 2. ABP on a FIFO link, but with NO sequence bit -- safety ===")
    nobit = check(build_fifo(use_bit=False, duplicating=True))
    if nobit.ok:
        print("  clean (unexpected!)")
    else:
        print(f"  BUG FOUND -- invariant '{nobit.invariant}' violated (the duplicate is delivered twice):")
        _print_trace(nobit)

    print("\n=== 3. ABP on a FIFO link, WITH the bit -- safety ===")
    safe = check(build_fifo(use_bit=True, duplicating=True))
    print(f"  in-order, no over-delivery: {'OK' if safe.ok else 'FAIL'} ({safe.states_explored} states)")

    print("\n=== 4. ABP liveness over the lossy FIFO link (the weak-vs-strong lesson) ===")
    model = build_fifo(use_bit=True)
    goal: Callable[[Slot], bool] = lambda s: s.r_idx == N  # noqa: E731  -- eventually all delivered
    delivers = ["data:deliver", "ack:deliver"]

    weak = check_liveness(model, goal=goal, goal_name="all-delivered", fair=["sender:send", *delivers])
    print(f"  under WEAK fairness on delivery:   {'OK' if weak.ok else 'FAILS'}"
          f"{'' if weak.ok else ' -- the link can drop forever (lasso below)'}")
    if not weak.ok:
        _print_trace(weak)

    strong = check_liveness(
        model, goal=goal, goal_name="all-delivered", fair=["sender:send"], fair_strong=delivers
    )
    print(f"\n  under STRONG fairness on delivery: {'OK' if strong.ok else 'FAILS'}"
          f"{' -- a frame offered infinitely often must eventually land' if strong.ok else ''}")

    print("\n--- improvement note for musil ---")
    print("  The channel kit (musil.channels) models only UNORDERED links. ABP, sliding-window, and")
    print("  any sequence-number protocol assume FIFO. A `fifo=True` mode on channel_actions (a slot")
    print("  or bounded queue instead of a frozenset) would let the kit express these directly,")
    print("  instead of every example hand-rolling its own ordered channel as Part 2 does here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
