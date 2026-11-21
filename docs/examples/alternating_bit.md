# Alternating Bit Protocol: and the channel it assumes

**What this teaches:** the oldest data-link protocol that works, and the assumption that makes it
work. ABP tags each frame with a one-bit sequence number and retransmits until the bit is echoed
back. That single bit lets the receiver tell a *fresh* message from a *retransmission*. The example
also surfaces a real limitation of musil's channel kit. It models only **unordered** links, while
ABP assumes **FIFO**.

## The story

A sender pushes a stream of messages to a receiver over a lossy link. Each frame carries a bit (0,
1, 0, 1, …). The sender retransmits the current frame until it sees that bit echoed in an ack, then
flips the bit and moves to the next message. The receiver delivers a frame only when its bit matches
the bit it expects, and echoes the frame's bit either way.

Two guarantees are required:

- **Safety**: the receiver never delivers a frame out of order or twice.
- **Liveness**: every message is eventually delivered.

State is modelled as counts, not payloads: `r_idx` is how many messages the receiver has delivered,
`s_idx` how many the sender has had acked. The sender's bit is `s_idx % 2`, the receiver's expected
bit is `r_idx % 2`. Both derived, so they cannot drift.

## 1. ABP needs a FIFO channel

Point musil's channel kit (`channel_actions`) at ABP. The kit models an **unordered** network
(reordering for free) which is the wrong channel for ABP. `check` proves it unsafe:

```
UNSAFE -- invariant 'in-order' violated. ABP needs FIFO; the kit is unordered:
  → sender:send: data=frozenset({(0, 0)})
  → data:deliver:(0, 0): r_idx=1, acks={0}
  → ... (sender advances to message 1, frame (1, 1) sent)
  → data:deliver:(1, 1): r_idx=2, data still holds the stale (0, 0)
  → data:deliver:(0, 0): r_idx=3, bad=True
```

The one-bit counter wraps: message 0 and message 2 both carry bit 0. A two-generations-old frame
`(0, 0)` survives in the unordered set until the receiver expects bit 0 again (`r_idx = 2`), then is
wrongly accepted. This is a true property of ABP (it assumes order-preserving links) not a modelling
mistake.

## 2. Why the bit exists

On a single-slot **FIFO** link that can *duplicate*, drop the sequence bit and the receiver delivers
a duplicated frame twice. The shortest trace is 3 steps:

```
BUG FOUND -- invariant 'in-order' violated (the duplicate is delivered twice):
  → sender:send: data=(0, 0)
  → data:deliver: r_idx=1   (delivered once; link keeps the frame)
  → data:deliver: r_idx=2, bad=True   (same frame delivered again)
```

## 3. The bit fixes it

Put the bit back. On the FIFO link the receiver rejects the mismatched-bit duplicate, and `check` is
clean:

```
in-order, no over-delivery: OK (30 states)
```

## 4. Weak fairness is not enough

This is the lesson the README points at: strong fairness is "what you need for delivery over a lossy
channel." Over a lossy link, "every message is eventually delivered" is **false** under weak
fairness. A fair scheduler is allowed to drop forever, because the deliver action is not
*continuously* enabled (after a drop the slot is empty until the sender re-sends):

```
under WEAK fairness on delivery:   FAILS -- the link can drop forever (lasso below)
  --- loops forever ---
  ↺ sender:send: data=(0, 2)
  ↺ data:drop:   data=None
```

Under **strong** fairness it holds. A frame offered infinitely often (the sender keeps re-sending)
must eventually be delivered:

```
under STRONG fairness on delivery: OK -- a frame offered infinitely often must eventually land
```

```python
check_liveness(model, goal=lambda s: s.r_idx == N, fair=["sender:send"], fair_strong=["data:deliver", "ack:deliver"])
```

Pick the weakest fairness that makes the property hold; here weak is genuinely too weak, and that is
the point.

## Improvement note for musil

The channel kit (`musil.channels`) models only **unordered** links. ABP, sliding-window, and any
sequence-number protocol assume FIFO. A `fifo=True` mode on `channel_actions` (a slot or bounded
queue instead of a frozenset) would let the kit express these directly, instead of every example
hand-rolling its own ordered channel as this one does.

Run it: `python examples/alternating_bit.py`
