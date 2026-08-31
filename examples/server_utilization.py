"""Steady-state rates, warm-up, and the best/worst policy — reward rates over a server, exact.

A server is BUSY or IDLE. Jobs arrive and are served probabilistically. The interesting quantities are RATES,
not one-off probabilities, and musil computes them exactly as `fractions.Fraction`:

- `long_run_reward` — the long-run AVERAGE of a per-state reward: the steady-state UTILISATION (fraction of
  time BUSY) and a REVENUE rate (BUSY earns, IDLE costs). The steady-state / `R=?[S]` answer.
- `transient_distribution` — the WARM-UP: the probability the server is BUSY after exactly k steps, starting
  IDLE. It climbs toward the steady state but is not there yet — the point-in-time distribution, not the limit.
- `long_run_reward_mdp` — when the server can be run in an ECO or a TURBO mode (a scheduler choice), the BEST
  and WORST long-run utilisation over all policies. The exact max/min steady-state rate over schedulers.

Run: python examples/server_utilization.py
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from musil import Action, Model, long_run_reward, long_run_reward_mdp, transient_distribution


@dataclass(frozen=True)
class Server:
    busy: bool


# The base DTMC -- the ECO server. IDLE: a job arrives or not (1/2 each). BUSY: finishes or keeps working;
# `work` is weighted 3 to `finish`'s 1, so it stays busy with probability 3/4.
_IDLE = [
    Action("arrive", enabled=lambda s: not s.busy, apply=lambda s: Server(True)),
    Action("wait", enabled=lambda s: not s.busy, apply=lambda s: Server(False)),
]
ECO = Model(
    init=Server(busy=False),
    actions=[
        *_IDLE,
        Action("finish", enabled=lambda s: s.busy, apply=lambda s: Server(False)),
        Action("work", enabled=lambda s: s.busy, apply=lambda s: Server(True)),  # weighted 3 -> stays busy 3/4
    ],
    terminal=lambda s: False,  # it runs forever
)

# The MDP: the same server, but BUSY can also run in a TURBO regime (finish 1 : work 1 -> frees up faster).
# A scheduler picks ECO or TURBO at each busy step; `_modes` groups the actions into the two moves.
SERVER_MDP = Model(
    init=Server(busy=False),
    actions=[
        *ECO.actions,  # arrive, wait, finish (eco), work (eco)
        Action("finish_t", enabled=lambda s: s.busy, apply=lambda s: Server(False)),  # turbo finish
        Action("work_t", enabled=lambda s: s.busy, apply=lambda s: Server(True)),  # turbo work (weight 1)
    ],
    terminal=lambda s: False,
)


def _weight(name: str, _s: Server) -> int:
    return 3 if name == "work" else 1  # eco stays busy 3:1; every other action is weight 1


def _utilisation(s: Server) -> int:
    return 1 if s.busy else 0  # long-run average of this = fraction of time BUSY


def _revenue(s: Server) -> int:
    return 10 if s.busy else -1  # BUSY earns 10 per step, IDLE costs 1


def _modes(s: Server, enabled: tuple[Action[Server], ...]) -> list[Sequence[Action[Server]]]:
    """The scheduler's per-state moves: IDLE has one (the arrive/wait coin); BUSY chooses ECO (stay busy 3/4)
    or TURBO (free up faster, 1/2)."""
    if not s.busy:
        return [list(enabled)]
    eco = [a for a in enabled if a.name in ("finish", "work")]
    turbo = [a for a in enabled if a.name in ("finish_t", "work_t")]
    return [eco, turbo]


if __name__ == "__main__":
    util = long_run_reward(ECO, _utilisation, weight=_weight)
    revenue = long_run_reward(ECO, _revenue, weight=_weight)
    print(f"steady-state utilisation (fraction BUSY) = {util}")  # 2/3
    print(f"steady-state revenue rate per step       = {revenue}")  # 19/3

    warmup = [transient_distribution(ECO, k, weight=_weight)[Server(True)] for k in range(5)]
    print(f"P(BUSY at step k=0..4), from IDLE        = {[str(p) for p in warmup]}")  # 0, 1/2, 5/8, ... -> 2/3

    best = long_run_reward_mdp(SERVER_MDP, _utilisation, moves=_modes, weight=_weight, optimize="max")
    worst = long_run_reward_mdp(SERVER_MDP, _utilisation, moves=_modes, weight=_weight, optimize="min")
    print(f"best-policy utilisation  (ECO)           = {best}")  # 2/3
    print(f"worst-policy utilisation (TURBO)         = {worst}")  # 1/2

    # Exact rational answers -- assert the closed forms.
    assert util == Fraction(2, 3)
    assert revenue == Fraction(19, 3)
    assert warmup == [Fraction(0), Fraction(1, 2), Fraction(5, 8), Fraction(21, 32), Fraction(85, 128)]
    assert (best, worst) == (Fraction(2, 3), Fraction(1, 2))
    print("\nRates are steady-state averages; the warm-up shows the transient climb toward them.")
