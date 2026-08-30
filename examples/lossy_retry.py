"""Exact quantitative answers over a lossy link — the probabilistic layer end to end.

A message is sent over a link that delivers each attempt with probability 1/2, otherwise drops it and the
sender retries. ``sim`` would SAMPLE this (Monte-Carlo); ``musil.probabilistic`` instead answers the exact
questions a stochastic system needs, as ``fractions.Fraction`` with no floating-point error:

- ``reach_probability`` — the probability the message is eventually delivered (here 1, almost surely).
- ``reach_probability(..., steps=k)`` — the probability it is delivered within ``k`` attempts: ``1-(1/2)^k``.
- ``expected_reward`` — the expected number of attempts to deliver: ``1/p = 2``.
- ``expected_reward_mdp`` — when the sender may CHOOSE a "fast" link (succeeds 1/2, cost 1 per attempt) or a
  "careful" link (succeeds 2/3, cost 2), the minimal expected cost over all strategies, and which link a
  cost-minimising sender picks.

Run: python examples/lossy_retry.py
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from musil import Action, Model, expected_reward, expected_reward_mdp, reach_probability


@dataclass(frozen=True)
class Link:
    status: str  # "sending" or "delivered"


def _delivered(s: Link) -> bool:
    return s.status == "delivered"


def _sending(s: Link) -> bool:
    return s.status == "sending"


# A single link, retrying forever until it gets through. The state is just the status (the attempt count is
# NOT in the state), so the reachable graph is finite: each attempt delivers (ack) or drops and loops back.
RETRY = Model(
    init=Link("sending"),
    actions=[
        Action("ack", enabled=_sending, apply=lambda s: Link("delivered")),  # weight 1
        Action("drop", enabled=_sending, apply=lambda s: Link("sending")),  # weight 1 -> each is 1/2
    ],
    terminal=_delivered,
)


# The same link, but the sender chooses a "fast" or "careful" strategy each attempt (an MDP). The careful
# ack is weighted 2:1 over its drop, so it succeeds with probability 2/3; the fast ack is 1:1, i.e. 1/2.
MDP = Model(
    init=Link("sending"),
    actions=[
        Action("fast_ack", enabled=_sending, apply=lambda s: Link("delivered")),
        Action("fast_drop", enabled=_sending, apply=lambda s: Link("sending")),
        Action("careful_ack", enabled=_sending, apply=lambda s: Link("delivered")),
        Action("careful_drop", enabled=_sending, apply=lambda s: Link("sending")),
    ],
    terminal=_delivered,
)


def _by_link(_s: Link, enabled: tuple[Action[Link], ...]) -> list[Sequence[Action[Link]]]:
    """The scheduler's choice: use the fast link (both its actions) or the careful link."""
    fast = [a for a in enabled if a.name.startswith("fast")]
    careful = [a for a in enabled if a.name.startswith("careful")]
    groups: list[Sequence[Action[Link]]] = []
    if fast:
        groups.append(fast)
    if careful:
        groups.append(careful)
    return groups


def _weight(name: str, _s: Link) -> int:
    return 2 if name == "careful_ack" else 1  # careful ack:drop = 2:1 -> 2/3 success; fast is 1:1 -> 1/2


def _cost(name: str, _s: Link) -> int:
    return 1 if name.startswith("fast") else 2  # a careful attempt costs twice a fast one


if __name__ == "__main__":
    delivered_prob = reach_probability(RETRY, _delivered)
    print(f"P(eventually delivered)      = {delivered_prob}")  # 1: almost surely

    within = [reach_probability(RETRY, _delivered, steps=k) for k in range(1, 5)]
    print(f"P(delivered within k=1..4)   = {[str(p) for p in within]}")  # 1/2, 3/4, 7/8, 15/16

    attempts = expected_reward(RETRY, _delivered)
    print(f"E[attempts to deliver]       = {attempts}")  # 2 = 1/p

    min_cost = expected_reward_mdp(MDP, _delivered, moves=_by_link, weight=_weight, cost=_cost)
    print(f"min E[cost] over strategies  = {min_cost}")  # 2: the fast link (cost 1, 1/2) beats careful

    # Everything above is exact rational arithmetic — assert the closed forms, no floating point.
    assert delivered_prob == Fraction(1)
    assert within == [Fraction(1, 2), Fraction(3, 4), Fraction(7, 8), Fraction(15, 16)]
    assert attempts == Fraction(2)
    assert min_cost == Fraction(2)
    print("\nAll exact-fraction answers match their closed forms.")
