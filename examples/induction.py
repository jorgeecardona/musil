"""Induction — proving an invariant beyond the explored scope, and reading a counterexample-to-induction.

`check` is exhaustive only up to the states it sweeps (and up to `max_states`). `check_inductive` proves an
invariant a different way — by k-induction over the transition relation — so a pass holds at UNBOUNDED depth:
every reachable state, at any scope, not just the ones enumerated. The price is that you supply a finite
`domain` of candidate states to quantify over, and it MUST include unreachable ones (1-induction over only the
reachable set proves nothing `check` didn't already).

The interesting case is an invariant that is TRUE on every reachable state yet not INDUCTIVE. Here a counter
steps by two — reachable values are `{0, 2, 4, 6, 8}` — and the natural bound `x <= 8` holds on all of them,
so `check` is green. But `x <= 8` is not inductive: from the UNREACHABLE odd pre-state `x = 7` (which still
satisfies `x <= 8`) one step reaches `x = 9`, breaking it. `check_inductive` returns exactly that
counterexample-to-induction, and the fix is to STRENGTHEN the invariant (add `x` is even) so the bad pre-state
no longer satisfies the antecedent — not to widen the scope.

This is the whole IC3/PDR-style workflow in miniature: a green `check` up to a bound, an inductive proof for
all depths, and a CTI that tells you how to strengthen. See `src/musil/INDUCTION_NOTES.md`.

Run: python examples/induction.py
"""

from __future__ import annotations

from dataclasses import dataclass

from musil import Action, Model, check
from musil.induction import check_inductive


@dataclass(frozen=True)
class Counter:
    x: int


COUNTER: Model[Counter] = Model(
    init=Counter(0),
    actions=[Action("step", enabled=lambda s: s.x < 8, apply=lambda s: Counter(s.x + 2))],
    terminal=lambda s: s.x == 8,
)

# The candidate domain the induction quantifies over: 0..9, INCLUDING the unreachable odd states. Without the
# unreachable ones, 1-induction is trivially true for anything `check` already passes and proves nothing new.
DOMAIN = [Counter(x) for x in range(10)]


def within_bound(s: Counter) -> bool:
    return s.x <= 8  # true on every reachable state, but NOT inductive


def within_bound_and_even(s: Counter) -> bool:
    return s.x <= 8 and s.x % 2 == 0  # the strengthened, inductive invariant


if __name__ == "__main__":
    bounded = check(Model(init=COUNTER.init, actions=COUNTER.actions, invariants={"x<=8": within_bound}, terminal=COUNTER.terminal))
    print(f"check (bounded sweep) says x <= 8 holds: {bounded.ok}  — over the reachable {{0,2,4,6,8}}")

    weak = check_inductive(COUNTER, within_bound, DOMAIN)
    print(f"\ncheck_inductive on 'x <= 8': proven = {weak.proven}")
    print(f"  counterexample-to-induction: {weak.state} --step--> {weak.successor}  (the pre-state is unreachable)")
    assert not weak.proven and weak.failure == "step"
    assert weak.state == Counter(7) and weak.successor == Counter(9)

    strong = check_inductive(COUNTER, within_bound_and_even, DOMAIN)
    print(f"\ncheck_inductive on the strengthened 'x <= 8 and x even': proven = {strong.proven}")
    print("  => the invariant now holds at UNBOUNDED depth — every reachable state, at any scope.")
    assert strong.proven

    print("\nA green check proved it up to a bound; induction proved it for all depths — once strengthened past the CTI.")
