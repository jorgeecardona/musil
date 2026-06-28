"""Leader election — why a quorum is what stops two leaders, and why elections can livelock.

A cluster of nodes must agree on a single leader, even though nodes campaign concurrently and the
network can split. This is the textbook distributed-systems target, and the heart of Raft/Paxos. The
model captures the essential rule: a node starts an election by bumping its *term* (an ever-increasing
round number) and voting for itself; other nodes grant at most one vote per term; a candidate that
collects enough votes becomes leader.

Three results, each one `check` / `check_liveness` call:

  1. NO QUORUM (safety). If a node can declare itself leader on its own vote, two nodes elected in the
     same term both win — a split brain. `check` returns the shortest trace to two leaders.

  2. QUORUM (safety). Require a *majority* of votes and that can't happen: each node votes once per
     term, so two candidates can't both reach a majority in the same term. `check` is clean — "at
     most one leader per term," the core election-safety property.

  3. LIVENESS. "A leader is eventually elected" is FALSE in general: every node can campaign at once,
     split the vote (no one gets a majority), time out, and repeat forever — the *split-vote livelock*.
     This is exactly why real Raft adds randomized election timeouts (so one node usually campaigns
     alone); pure fairness can't conjure that, and musil shows the livelock as a lasso.

Run:  python examples/leader_election.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from musil import Action, Model, check, check_liveness

N = 3  # nodes 0..2
MAJORITY = 2  # of 3
MAX_TERM = 2  # bound the rounds so the model is finite


@dataclass(frozen=True)
class Cluster:
    term: tuple[int, ...] = (0,) * N  # each node's current term (round number)
    role: tuple[str, ...] = ("follower",) * N  # follower | candidate | leader
    votes: frozenset[tuple[int, int, int]] = frozenset()  # (term, voter, candidate) ballots cast


def _set(t: tuple[int, ...], i: int, v: int) -> tuple[int, ...]:
    return (*t[:i], v, *t[i + 1 :])


def _setr(t: tuple[str, ...], i: int, v: str) -> tuple[str, ...]:
    return (*t[:i], v, *t[i + 1 :])


def _votes_for(s: Cluster, candidate: int, term: int) -> int:
    return sum(1 for (t, _voter, c) in s.votes if t == term and c == candidate)


def _voted_already(s: Cluster, voter: int, term: int) -> bool:
    return any(t == term and v == voter for (t, v, _c) in s.votes)


def _one_leader_per_term(s: Cluster) -> bool:
    """Election safety: no two nodes are leaders in the same term (an old-term leader is harmless —
    followers reject it; two leaders in the *same* term is the real split brain)."""
    terms = [s.term[i] for i in range(N) if s.role[i] == "leader"]
    return len(set(terms)) == len(terms)


def build(*, threshold: int) -> Model[Cluster]:
    """`threshold` votes are needed to win. `MAJORITY` = real quorum (safe); `1` = self-appoint (bug)."""
    actions: list[Action[Cluster]] = []
    for i in range(N):
        # campaign: bump own term, become candidate, vote for self
        actions.append(Action(
            f"campaign:{i}",
            lambda s, i=i: s.role[i] != "leader" and s.term[i] < MAX_TERM,
            lambda s, i=i: replace(
                s, term=_set(s.term, i, s.term[i] + 1), role=_setr(s.role, i, "candidate"),
                votes=s.votes | {(s.term[i] + 1, i, i)},
            ),
        ))
        # win: a candidate with enough votes in its term becomes leader
        actions.append(Action(
            f"win:{i}",
            lambda s, i=i: s.role[i] == "candidate" and _votes_for(s, i, s.term[i]) >= threshold,
            lambda s, i=i: replace(s, role=_setr(s.role, i, "leader")),
        ))
        for j in range(N):
            if j == i:
                continue
            # j grants its vote to candidate i (once per term), adopting i's term
            actions.append(Action(
                f"vote:{j}->{i}",
                lambda s, i=i, j=j: s.role[i] == "candidate" and s.term[j] <= s.term[i]
                and not _voted_already(s, j, s.term[i]),
                lambda s, i=i, j=j: replace(
                    s, votes=s.votes | {(s.term[i], j, i)},
                    term=_set(s.term, j, s.term[i]), role=_setr(s.role, j, "follower"),
                ),
            ))
    # a state with no enabled action is a legitimate end of this bounded model (a leader elected, or
    # a stuck split-vote that the liveness check catches) — not a deadlock bug. Reuse the real guards.
    return Model(
        init=Cluster(),
        actions=actions,
        invariants={"one-leader-per-term": _one_leader_per_term},
        terminal=lambda s: not any(a.enabled(s) for a in actions),
    )


def main() -> int:
    print("=== 1. NO QUORUM (a node self-appoints on its own vote) — safety ===")
    bad = check(build(threshold=1))
    if bad.ok:
        print("  no split brain: OK (unexpected!)")
    else:
        print(f"  SPLIT BRAIN -- invariant '{bad.invariant}' violated (two leaders in one term):")
        print("  " + str(bad).replace("\n", "\n  "))

    print("\n=== 2. QUORUM (a majority is required) — safety ===")
    good = check(build(threshold=MAJORITY))
    print(f"  at most one leader per term: {'OK' if good.ok else 'FAIL'} ({good.states_explored} states)")

    print("\n=== 3. Liveness: is a leader always eventually elected? ===")
    live = check_liveness(build(threshold=MAJORITY),
                          goal=lambda s: any(r == "leader" for r in s.role), goal_name="some-leader")
    print(f"  eventually a leader: {'OK' if live.ok else 'FAILS'} "
          f"{'' if live.ok else '— SPLIT-VOTE LIVELOCK: all campaign at once, no majority, repeat'}")
    print("\n  Lesson: quorum gives safety (never two leaders); but liveness needs more than fairness")
    print("  — real Raft breaks the split-vote with randomized timeouts so one node campaigns alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
