"""Producer-consumer on a bounded buffer -- the check-then-act race, and the atomic fix.

The classic concurrent queue. Producers add to a buffer of capacity ``CAP``; consumers remove. The
naive producer is *non-atomic*: it first CHECKS that there is room, then -- as a separate step --
COMMITS the insert. musil's interleaving sweep finds the ordering where two producers both pass the
"there is room" check while a single slot is free, and then both commit, overflowing the buffer past
its capacity. The shortest counterexample is printed.

The fix makes test-and-insert a single atomic action. musil then verifies the count stays within
``[0, CAP]`` across every interleaving with no deadlock, and that every produced item is eventually
consumed (convergence).

This is `lost_update.py`'s race grown into a real data structure.

Run: python examples/producer_consumer.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Invariant, Model, check, check_liveness

CAP = 1  # buffer capacity -- a single free slot is enough to expose the race
PRODUCERS = 2  # each produces one item
CONSUMERS = 2  # each consumes one item


@dataclass(frozen=True)
class Buffer:
    """The shared buffer. ``count`` is how many items it holds; each producer/consumer is a small
    phase machine. A producer goes idle -> ready (it has seen room) -> done; a consumer goes
    idle -> ready (it has seen an item) -> done. ``count`` always equals produced minus consumed."""

    count: int = 0
    producers: tuple[str, ...] = ("idle",) * PRODUCERS
    consumers: tuple[str, ...] = ("idle",) * CONSUMERS


def _set(seq: tuple[str, ...], i: int, val: str) -> tuple[str, ...]:
    """Return ``seq`` with index ``i`` replaced -- the immutable-update idiom for a tuple field."""
    return (*seq[:i], val, *seq[i + 1 :])


def naive_actions() -> list[Action[Buffer]]:
    """Non-atomic actors: the room/empty CHECK and the COMMIT are separate steps, so a decision can
    go stale in between. That gap is the bug. (Default-arg capture pins the loop index per action,
    avoiding late-binding.)"""
    actions: list[Action[Buffer]] = []
    for i in range(PRODUCERS):
        actions.append(
            Action(
                f"P{i}_check",  # saw a free slot...
                lambda s, _i=i: s.producers[_i] == "idle" and s.count < CAP,
                lambda s, _i=i: replace(s, producers=_set(s.producers, _i, "ready")),
            )
        )
        actions.append(
            Action(
                f"P{i}_commit",  # ...and commits without re-checking
                lambda s, _i=i: s.producers[_i] == "ready",
                lambda s, _i=i: replace(s, count=s.count + 1, producers=_set(s.producers, _i, "done")),
            )
        )
    for j in range(CONSUMERS):
        actions.append(
            Action(
                f"C{j}_check",  # saw an item...
                lambda s, _j=j: s.consumers[_j] == "idle" and s.count > 0,
                lambda s, _j=j: replace(s, consumers=_set(s.consumers, _j, "ready")),
            )
        )
        actions.append(
            Action(
                f"C{j}_commit",  # ...and removes without re-checking
                lambda s, _j=j: s.consumers[_j] == "ready",
                lambda s, _j=j: replace(s, count=s.count - 1, consumers=_set(s.consumers, _j, "done")),
            )
        )
    return actions


def atomic_actions() -> list[Action[Buffer]]:
    """The fix: test-and-insert (and test-and-remove) as a SINGLE atomic action, so the guard cannot
    go stale between deciding and acting -- one step does both the check and the update."""
    actions: list[Action[Buffer]] = []
    for i in range(PRODUCERS):
        actions.append(
            Action(
                f"P{i}_put",
                lambda s, _i=i: s.producers[_i] == "idle" and s.count < CAP,
                lambda s, _i=i: replace(s, count=s.count + 1, producers=_set(s.producers, _i, "done")),
            )
        )
    for j in range(CONSUMERS):
        actions.append(
            Action(
                f"C{j}_get",
                lambda s, _j=j: s.consumers[_j] == "idle" and s.count > 0,
                lambda s, _j=j: replace(s, count=s.count - 1, consumers=_set(s.consumers, _j, "done")),
            )
        )
    return actions


def _all_done(s: Buffer) -> bool:
    return all(p == "done" for p in s.producers) and all(c == "done" for c in s.consumers)


# the buffer must never overflow its capacity or underflow below empty
_INVARIANTS: dict[str, Invariant[Buffer]] = {"within-capacity": lambda s: 0 <= s.count <= CAP}


def naive_model() -> Model[Buffer]:
    return Model(init=Buffer(), actions=naive_actions(), invariants=_INVARIANTS, terminal=_all_done)


def atomic_model() -> Model[Buffer]:
    return Model(init=Buffer(), actions=atomic_actions(), invariants=_INVARIANTS, terminal=_all_done)


def main() -> int:
    print("=== naive buffer (check, then commit -- non-atomic) ===")
    print(check(naive_model()))

    print("\n=== atomic buffer (test-and-insert in one step) ===")
    print(check(atomic_model()))
    live = check_liveness(
        atomic_model(),
        goal=_all_done,
        goal_name="every item produced and consumed",
    )
    print(f"liveness (every item eventually consumed): {'OK' if live.ok else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
