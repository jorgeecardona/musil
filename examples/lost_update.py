"""A lost-update race: two non-atomic increments of a shared counter.

Each actor reads the counter, then writes back read+1, as two separate steps. musil's interleaving
sweep finds the ordering where both read the old value before either writes — so the counter ends at
1, not 2. The shortest counterexample trace is printed.

Run: python examples/lost_update.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check


@dataclass(frozen=True)
class Counter:
    x: int = 0
    a_reg: int | None = None  # A's read-but-not-yet-written value
    b_reg: int | None = None
    a_done: bool = False
    b_done: bool = False


MODEL = Model(
    init=Counter(),
    actions=[
        Action("A_read", lambda s: s.a_reg is None and not s.a_done, lambda s: replace(s, a_reg=s.x)),
        Action(
            "A_write",
            lambda s: s.a_reg is not None,
            lambda s: replace(s, x=(s.a_reg or 0) + 1, a_reg=None, a_done=True),
        ),
        Action("B_read", lambda s: s.b_reg is None and not s.b_done, lambda s: replace(s, b_reg=s.x)),
        Action(
            "B_write",
            lambda s: s.b_reg is not None,
            lambda s: replace(s, x=(s.b_reg or 0) + 1, b_reg=None, b_done=True),
        ),
    ],
    invariants={"both-increments-counted": lambda s: not (s.a_done and s.b_done) or s.x == 2},
    terminal=lambda s: s.a_done and s.b_done,
)


if __name__ == "__main__":
    print(check(MODEL))
