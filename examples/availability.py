"""Steady-state availability, until-probability, and recovery cost — the probabilistic layer's steady-state
and constrained answers, exact.

A replicated service cycles through health states forever: mostly HEALTHY, occasionally DEGRADED, sometimes
FAILED, then restarting. `sim` would SAMPLE this; `musil.probabilistic` answers the exact questions as
`fractions.Fraction`, no floating-point error:

- `long_run_probability` — the long-run FRACTION OF TIME the service is HEALTHY (steady-state availability),
  and the fraction FAILED. A stationary-distribution answer that is exact even though the chain never settles
  into a single state (it cycles forever).
- `reach_probability(..., avoid=...)` — the probability of hitting FAILED from DEGRADED WITHOUT first
  recovering to HEALTHY: the constrained (until) probability `P(¬healthy U failed)`. Compare it to the plain
  reachability, which is 1 (the chain reaches FAILED eventually almost surely).
- `expected_reward_mdp(..., optimize=...)` — when recovery can be STAGED (cheaper, one hop through a
  recovering state) or DIRECT (dearer, immediate), the MINIMAL and MAXIMAL expected cost to get back to
  HEALTHY over all recovery strategies.

Run: python examples/availability.py
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from fractions import Fraction

from musil import Action, Model, expected_reward_mdp, long_run_probability, reach_probability

HEALTHY, DEGRADED, FAILED, RECOVERING = "healthy", "degraded", "failed", "recovering"


@dataclass(frozen=True)
class Health:
    state: str


def _at(tag: str) -> Callable[[Health], bool]:
    return lambda s: s.state == tag


# The availability chain (a DTMC): HEALTHY mostly stays healthy (stay weighted 3 : degrade 1, so P=3/4),
# DEGRADED recovers or fails (1:1), FAILED restarts to DEGRADED. Irreducible -- it never settles, so the
# steady state is a genuine long-run average, not a state the chain ends in.
AVAILABILITY = Model(
    init=Health(DEGRADED),
    actions=[
        Action("stay", enabled=_at(HEALTHY), apply=lambda s: Health(HEALTHY)),
        Action("degrade", enabled=_at(HEALTHY), apply=lambda s: Health(DEGRADED)),
        Action("recover", enabled=_at(DEGRADED), apply=lambda s: Health(HEALTHY)),
        Action("fail", enabled=_at(DEGRADED), apply=lambda s: Health(FAILED)),
        Action("restart", enabled=_at(FAILED), apply=lambda s: Health(DEGRADED)),
    ],
    terminal=lambda s: False,  # it runs forever; there is no absorbing state
)


def _weight(name: str, _s: Health) -> int:
    return 3 if name == "stay" else 1  # HEALTHY stays with probability 3/4, degrades with 1/4


# The recovery MDP: from FAILED a strategy chooses STAGED (-> RECOVERING, cost 1, then a cost-1 finish) or
# DIRECT (-> HEALTHY, cost 3). Both reach HEALTHY almost surely, so min AND max expected cost are finite.
RECOVERY = Model(
    init=Health(FAILED),
    actions=[
        Action("staged", enabled=_at(FAILED), apply=lambda s: Health(RECOVERING)),
        Action("direct", enabled=_at(FAILED), apply=lambda s: Health(HEALTHY)),
        Action("finish", enabled=_at(RECOVERING), apply=lambda s: Health(HEALTHY)),
    ],
    terminal=_at(HEALTHY),
)


def _by_strategy(_s: Health, enabled: tuple[Action[Health], ...]) -> list[Sequence[Action[Health]]]:
    """Each recovery action is its own move: the strategy picks STAGED vs DIRECT at FAILED."""
    return [[a] for a in enabled]


def _cost(name: str, _s: Health) -> int:
    return {"staged": 1, "direct": 3, "finish": 1}[name]


if __name__ == "__main__":
    up = long_run_probability(AVAILABILITY, _at(HEALTHY), weight=_weight)
    down = long_run_probability(AVAILABILITY, _at(FAILED), weight=_weight)
    print(f"long-run availability P(healthy) = {up}")  # 4/7
    print(f"long-run P(failed)               = {down}")  # 1/7

    reach_failed = reach_probability(AVAILABILITY, _at(FAILED), weight=_weight)
    reach_failed_direct = reach_probability(AVAILABILITY, _at(FAILED), weight=_weight, avoid=_at(HEALTHY))
    print(f"P(eventually failed)             = {reach_failed}")  # 1: almost surely, over the long run
    print(f"P(failed before recovering)      = {reach_failed_direct}")  # 1/2: the until-probability from DEGRADED

    min_cost = expected_reward_mdp(RECOVERY, _at(HEALTHY), moves=_by_strategy, cost=_cost, optimize="min")
    max_cost = expected_reward_mdp(RECOVERY, _at(HEALTHY), moves=_by_strategy, cost=_cost, optimize="max")
    print(f"min E[recovery cost]             = {min_cost}")  # 2: staged (1 + 1) beats direct (3)
    print(f"max E[recovery cost]             = {max_cost}")  # 3: the direct strategy, the worst case

    # Everything is exact rational arithmetic -- assert the closed forms, no floating point.
    assert (up, down) == (Fraction(4, 7), Fraction(1, 7))
    assert reach_failed == Fraction(1)
    assert reach_failed_direct == Fraction(1, 2)
    assert (min_cost, max_cost) == (Fraction(2), Fraction(3))
    print("\nAll exact-fraction answers match their closed forms.")
