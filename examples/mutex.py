"""Peterson's algorithm — the classic mutual-exclusion proof, by exhaustive interleaving.

Two processes contend for a critical section using flags + a turn variable. musil explores every
interleaving and verifies the invariant "the two are never in the critical section at once" — and
that the protocol can't deadlock. This is the textbook model-checking example.

Run: python examples/mutex.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check


@dataclass(frozen=True)
class Peterson:
    pc0: str = "idle"  # idle -> want -> wait -> crit -> idle
    pc1: str = "idle"
    flag0: bool = False
    flag1: bool = False
    turn: int = 0


MODEL = Model(
    init=Peterson(),
    actions=[
        # process 0
        Action("p0_set", lambda s: s.pc0 == "idle", lambda s: replace(s, flag0=True, pc0="want")),
        Action("p0_turn", lambda s: s.pc0 == "want", lambda s: replace(s, turn=1, pc0="wait")),
        Action(
            "p0_enter",
            lambda s: s.pc0 == "wait" and (not s.flag1 or s.turn == 0),
            lambda s: replace(s, pc0="crit"),
        ),
        Action("p0_exit", lambda s: s.pc0 == "crit", lambda s: replace(s, flag0=False, pc0="idle")),
        # process 1 (symmetric)
        Action("p1_set", lambda s: s.pc1 == "idle", lambda s: replace(s, flag1=True, pc1="want")),
        Action("p1_turn", lambda s: s.pc1 == "want", lambda s: replace(s, turn=0, pc1="wait")),
        Action(
            "p1_enter",
            lambda s: s.pc1 == "wait" and (not s.flag0 or s.turn == 1),
            lambda s: replace(s, pc1="crit"),
        ),
        Action("p1_exit", lambda s: s.pc1 == "crit", lambda s: replace(s, flag1=False, pc1="idle")),
    ],
    invariants={"mutual-exclusion": lambda s: not (s.pc0 == "crit" and s.pc1 == "crit")},
)


if __name__ == "__main__":
    result = check(MODEL)
    print(result)
    print("mutual exclusion holds across every interleaving" if result.ok else "VIOLATION above")
