"""Vote tallying — the integrity properties a model checker *can* prove (and the one it can't).

"Secure voting" bundles two very different kinds of property. The **integrity** kind — every eligible
voter votes at most once, every cast ballot is counted exactly once, the announced tally equals the
ballots cast — is a state machine, and a careless concurrent tally can drop or double-count a vote.
That part musil checks. The **secrecy** kind — no one can tell how you voted, no one can coerce you —
is about what an observer can *infer*, which needs cryptography, not state enumeration. musil has no
notion of secrecy, so that part is explicitly out of scope here.

Two results on the integrity part:

  1. RACY TALLY (safety). Counting a ballot as read-then-write (read the running total, write total+1)
     lets two concurrent counts interleave and lose a vote — the classic lost update. `check` finds
     the trace where a counted ballot vanishes from the total.

  2. ATOMIC TALLY (safety). Count each ballot in one indivisible step and the total always equals the
     ballots counted, every eligible voter votes at most once, and the final tally equals the ballots
     cast. `check` is clean.

Run:  python examples/voting_tally.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check

ELIGIBLE = (0, 1, 2)  # the electoral roll — only these may cast a ballot


@dataclass(frozen=True)
class Election:
    cast: frozenset[int] = frozenset()  # voters who have cast a ballot
    counted: frozenset[int] = frozenset()  # ballots that have been tallied
    tally: int = 0  # the running total
    pending: frozenset[tuple[int, int]] = frozenset()  # (voter, total-it-read) — uncommitted reads


def _eligible_only(s: Election) -> bool:
    return s.cast <= frozenset(ELIGIBLE)  # nobody off the roll voted


def _tally_matches_counted(s: Election) -> bool:
    return s.tally == len(s.counted)  # the total reflects exactly the ballots counted — no loss/dup


def _no_overcount(s: Election) -> bool:
    return s.tally <= len(s.cast)  # never count more than were cast


_INVARIANTS = {
    "eligible-only": _eligible_only,
    "tally-matches-counted": _tally_matches_counted,
    "no-overcount": _no_overcount,
}


def build_atomic() -> Model[Election]:
    """Count each ballot in one indivisible step — the total can't be corrupted by interleaving."""
    actions: list[Action[Election]] = []
    for v in ELIGIBLE:
        actions.append(Action(f"cast:{v}", lambda s, v=v: v not in s.cast,
                              lambda s, v=v: replace(s, cast=s.cast | {v})))
        actions.append(Action(
            f"count:{v}", lambda s, v=v: v in s.cast and v not in s.counted,
            lambda s, v=v: replace(s, counted=s.counted | {v}, tally=s.tally + 1),
        ))
    return Model(init=Election(), actions=actions, invariants=_INVARIANTS,
                 terminal=lambda s: s.counted == s.cast == frozenset(ELIGIBLE))


def build_racy() -> Model[Election]:
    """Tally as read-then-write: read the running total, then later write total+1. Two counts that
    both read the same total before either writes lose a vote."""
    actions: list[Action[Election]] = []
    for v in ELIGIBLE:
        actions.append(Action(f"cast:{v}", lambda s, v=v: v not in s.cast,
                              lambda s, v=v: replace(s, cast=s.cast | {v})))
        actions.append(Action(  # read the current total (no increment yet)
            f"read:{v}",
            lambda s, v=v: v in s.cast and v not in s.counted
            and not any(pv == v for pv, _ in s.pending),
            lambda s, v=v: replace(s, pending=s.pending | {(v, s.tally)}),
        ))
        actions.append(Action(  # write back the total it read, plus one
            f"write:{v}",
            lambda s, v=v: any(pv == v for pv, _ in s.pending),
            lambda s, v=v: _commit(s, v),
        ))
    return Model(init=Election(), actions=actions, invariants=_INVARIANTS,
                 terminal=lambda s: s.counted == s.cast == frozenset(ELIGIBLE))


def _commit(s: Election, v: int) -> Election:
    snapshot = next(snap for pv, snap in s.pending if pv == v)
    entry = (v, snapshot)
    return replace(s, counted=s.counted | {v}, tally=snapshot + 1, pending=s.pending - {entry})


def main() -> int:
    print("=== 1. RACY TALLY (read-then-write count) — safety ===")
    racy = check(build_racy())
    if racy.ok:
        print("  integrity holds: OK (unexpected!)")
    else:
        print(f"  VOTE LOST -- invariant '{racy.invariant}' violated (a counted ballot vanished):")
        print("  " + str(racy).replace("\n", "\n  "))

    print("\n=== 2. ATOMIC TALLY (count in one step) — safety ===")
    atomic = check(build_atomic())
    print(f"  eligible-only, tally matches, no overcount: {'OK' if atomic.ok else 'FAIL'} "
          f"({atomic.states_explored} states)")

    print("\n  Checkable here: at-most-once, exactly-once counting, tally == ballots. NOT checkable")
    print("  here: ballot secrecy / coercion-resistance — those are cryptographic, not state-machine,")
    print("  properties, and musil has no notion of what an observer can infer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
