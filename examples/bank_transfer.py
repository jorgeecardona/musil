"""Bank transfer -- a lock-ordering deadlock, and the conservation law that survives the fix.

Two transfers run concurrently: one moves a unit A->B, the other B->A. Each locks its source account,
then its destination. The naive order deadlocks: the A->B transfer grabs A's lock while the B->A
transfer grabs B's lock, and now each waits forever for the lock the other holds. musil reports the
DEADLOCK with the shortest trace into it.

Locking the accounts in a fixed global order (lowest id first) breaks the circular wait. musil then
confirms two things about the fixed protocol: there is no reachable deadlock, and the conservation
invariant -- total money is never created or destroyed -- holds in every reachable state.

Run: python examples/bank_transfer.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check

TOTAL = 2  # the bank starts with account a = 2, b = 0


@dataclass(frozen=True)
class Bank:
    a: int = 2
    b: int = 0
    owner_a: str | None = None  # which transfer holds account a's lock (None = free)
    owner_b: str | None = None
    t1: str = "idle"  # transfer a->b: idle -> locked -> both -> done
    t2: str = "idle"  # transfer b->a


def _owner(s: Bank, acct: str) -> str | None:
    return getattr(s, f"owner_{acct}")


def _set_owner(s: Bank, acct: str, val: str | None) -> Bank:
    return replace(s, **{f"owner_{acct}": val})


def _phase(s: Bank, t: str) -> str:
    return getattr(s, t)


def _set_phase(s: Bank, t: str, val: str) -> Bank:
    return replace(s, **{t: val})


def _move(s: Bank, frm: str, to: str) -> Bank:
    return replace(s, **{frm: getattr(s, frm) - 1, to: getattr(s, to) + 1})


def _release(s: Bank, t: str) -> Bank:
    s = replace(s, owner_a=None if s.owner_a == t else s.owner_a)
    return replace(s, owner_b=None if s.owner_b == t else s.owner_b)


def _transfer(t: str, first: str, second: str, frm: str, to: str) -> list[Action[Bank]]:
    """Transfer ``t`` locks ``first`` then ``second``, then moves a unit ``frm`` -> ``to`` and releases."""
    return [
        Action(
            f"{t}_lock_{first}",
            lambda s: _phase(s, t) == "idle" and _owner(s, first) is None,
            lambda s: _set_phase(_set_owner(s, first, t), t, "locked"),
        ),
        Action(
            f"{t}_lock_{second}",
            lambda s: _phase(s, t) == "locked" and _owner(s, second) is None,
            lambda s: _set_phase(_set_owner(s, second, t), t, "both"),
        ),
        Action(
            f"{t}_commit",
            lambda s: _phase(s, t) == "both",
            lambda s: _set_phase(_release(_move(s, frm, to), t), t, "done"),
        ),
    ]


def _model(*, ordered: bool) -> Model[Bank]:
    t1 = _transfer("t1", "a", "b", "a", "b")  # a->b always locks a then b (source-first == ordered)
    # naive: t2 (b->a) locks its SOURCE b first -> crosses with t1. ordered: t2 also locks a first.
    t2 = _transfer("t2", "a", "b", "b", "a") if ordered else _transfer("t2", "b", "a", "b", "a")
    return Model(
        init=Bank(),
        actions=[*t1, *t2],
        invariants={"conservation": lambda s: s.a + s.b == TOTAL},
        terminal=lambda s: s.t1 == "done" and s.t2 == "done",
    )


def naive_model() -> Model[Bank]:
    return _model(ordered=False)


def ordered_model() -> Model[Bank]:
    return _model(ordered=True)


def main() -> int:
    print("=== naive (each transfer locks its SOURCE account first) ===")
    print(check(naive_model()))
    print("\n=== ordered (every transfer locks the lower-id account first) ===")
    print(check(ordered_model()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
