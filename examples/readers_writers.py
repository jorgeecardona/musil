"""Readers-writers -- mutual exclusion holds, but a naive policy starves the writer.

Many readers may hold the lock at once, or a single writer exclusively -- never both. The SAFETY
property (no reader reads while a writer writes; at most one writer) holds across every interleaving,
and musil proves it for both policies below. The subtler, temporal question is LIVENESS: will a
waiting writer ever get to write?

Under a reader-preference policy (a reader may enter whenever no writer is *writing*), readers can
keep handing the lock among themselves forever, so the lock count never drops to zero and a waiting
writer is starved. musil finds that fair cycle. A writer-preference policy (once a writer is waiting,
no NEW reader may enter) drains the readers and lets the writer in -- musil shows it always
eventually writes.

Run: python examples/readers_writers.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check, check_liveness

READERS = 2  # how many readers may hold the lock at once


@dataclass(frozen=True)
class Lock:
    readers: int = 0  # readers currently holding the lock
    writing: bool = False  # a writer currently holds the lock
    writer_waiting: bool = False  # a writer has announced it wants the lock


def _model(*, writer_pref: bool) -> Model[Lock]:
    actions: list[Action[Lock]] = [
        Action(
            "start_read",
            # reader-preference lets a reader in regardless of a waiting writer; writer-preference
            # blocks NEW readers once a writer is waiting (that is the whole difference).
            lambda s: not s.writing
            and s.readers < READERS
            and (not s.writer_waiting if writer_pref else True),
            lambda s: replace(s, readers=s.readers + 1),
        ),
        Action("stop_read", lambda s: s.readers > 0, lambda s: replace(s, readers=s.readers - 1)),
        Action(
            "want_write",
            lambda s: not s.writing and not s.writer_waiting,
            lambda s: replace(s, writer_waiting=True),
        ),
        Action(
            "start_write",
            lambda s: s.writer_waiting and s.readers == 0 and not s.writing,
            lambda s: replace(s, writing=True, writer_waiting=False),
        ),
        Action("stop_write", lambda s: s.writing, lambda s: replace(s, writing=False)),
    ]
    return Model(
        init=Lock(),
        actions=actions,
        invariants={"mutual-exclusion": lambda s: not (s.writing and s.readers > 0)},
    )


# fairness: assume the writer's own steps and reader release are eventually taken when due. The
# difference in outcome is then purely the policy, not an unfair scheduler.
_FAIR = ["want_write", "stop_read", "start_write"]


def main() -> int:
    print("=== safety (mutual exclusion) -- across every interleaving ===")
    print("  reader-preference:", check(_model(writer_pref=False)))
    print("  writer-preference:", check(_model(writer_pref=True)))

    print("\n=== liveness (does a waiting writer ever write?) ===")
    rp = check_liveness(_model(writer_pref=False), goal=lambda s: s.writing, goal_name="writer writes", fair=_FAIR)
    wp = check_liveness(_model(writer_pref=True), goal=lambda s: s.writing, goal_name="writer writes", fair=_FAIR)
    print(f"  reader-preference: {'OK' if rp.ok else 'WRITER CAN STARVE (fair cycle found)'}")
    print(f"  writer-preference: {'OK -- writer always eventually writes' if wp.ok else 'STILL STARVES'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
