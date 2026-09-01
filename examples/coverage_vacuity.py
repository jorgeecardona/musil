"""A green check can be meaningless — `coverage` and `invariant_coverage` say when.

`check` returning OK means no invariant broke on the reachable space. It does NOT mean the behaviour you
wrote was exercised, or that your invariants caught anything. Two silent failure modes:

- a **dead action** — one whose guard is never satisfiable in any reachable state, so it never fires. Usually
  a guard bug or dead code; the OK verdict hides that an interleaving you believed was covered never ran.
- a **vacuously-true invariant** — one that no action could ever break, so it passes for the wrong reason.
  It adds nothing, and worse, it can lull you into thinking a property is checked when it is not.

`coverage(model)` finds the first; `invariant_coverage(model)` finds the second (and confirms which
invariants are genuinely load-bearing — protected by a guard that would otherwise let a violation through).
Both run over the whole reachable graph, next to `check`, never inside it.

Here a tiny account passes `check` cleanly, yet has one of each. Run: python examples/coverage_vacuity.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check
from musil.metrics import coverage, invariant_coverage


@dataclass(frozen=True)
class Account:
    balance: int = 0
    status: str = "open"


MODEL = Model(
    init=Account(0, "open"),
    actions=[
        Action("deposit", lambda s: s.status == "open" and s.balance < 3, lambda s: replace(s, balance=s.balance + 1)),
        Action("withdraw", lambda s: s.status == "open" and s.balance > 0, lambda s: replace(s, balance=s.balance - 1)),
        # BUG: guarded on "frozen", a status nothing ever sets -> this action can never fire (dead code).
        Action("thaw", lambda s: s.status == "frozen", lambda s: replace(s, status="open")),
    ],
    invariants={
        # Load-bearing: the withdraw guard (balance > 0) is exactly what keeps this true; a withdraw
        # fired at balance 0 would drive it to -1. invariant_coverage will confirm the guard protects it.
        "non-negative-balance": lambda s: s.balance >= 0,
        # Vacuous: no action ever produces a status outside this set, so nothing can ever break it. It
        # passes, but it is not catching anything -- a false sense of coverage.
        "status-known": lambda s: s.status in {"open", "frozen", "closed"},
    },
    terminal=lambda s: False,
)


if __name__ == "__main__":
    result = check(MODEL)
    print(result)  # OK -- the sweep is green

    cov = coverage(MODEL)
    print()
    print(cov)  # flags 'thaw' as never enabled (dead)

    ic = invariant_coverage(MODEL)
    print()
    print(ic)  # 'non-negative-balance' load-bearing; 'status-known' candidate-vacuous

    # The green check hides a dead action and a vacuous invariant; the coverage reports surface both.
    assert result.ok
    assert cov.dead_actions == ("thaw",)
    assert ic.load_bearing == ("non-negative-balance",)
    assert ic.candidate_vacuous == ("status-known",)
    print("\nGreen check, yet: one dead action (thaw) and one vacuous invariant (status-known).")
