# Leader election: quorum, split brain, and the split-vote livelock

**What this teaches:** why a *quorum* (majority) is exactly what prevents two leaders, and why
electing a leader is a *liveness* problem that fairness alone can't solve. This is the heart of
Raft/Paxos, reduced to its essence.

## The model

A cluster of nodes (default 3) must agree on one leader. The essential rule, captured directly:

- a node starts an election by bumping its **term** (an ever-increasing round number) and voting for
  itself;
- every node grants **at most one vote per term**;
- a candidate that collects **`threshold`** votes in its term becomes leader.

`threshold = majority` is a real quorum; `threshold = 1` is "self-appoint."

## 1. No quorum → split brain

If one vote (your own) is enough to win, two nodes elected in the same term both become leader:

```
SPLIT BRAIN — invariant 'one-leader-per-term' violated:
  → campaign:0 / win:0   node 0 is leader in term 1 (1 vote)
  → campaign:1 / win:1   node 1 is leader in term 1 (1 vote)  ← two leaders, same term
```

## 2. Quorum → safe

Require a majority and it can't happen: each node votes once per term, so two candidates can't both
reach a majority in the same term. `check` is clean: **at most one leader per term**, the core
*election-safety* property. (Two leaders in *different* terms is fine: a stale, old-term leader is
rejected by followers.)

```
at most one leader per term: OK (681 states)
```

## 3. Liveness: and why it fails

"A leader is *eventually* elected" is **false** in general:

```
eventually a leader: FAILS — SPLIT-VOTE LIVELOCK: all campaign at once, no majority, repeat
```

Every node can campaign at the same time, split the vote three ways (no one gets a majority), time
out, and repeat. Forever. This is the real **split-vote livelock**, and it's exactly why production
Raft adds **randomized election timeouts**: they make it likely that one node campaigns alone.
That's an assumption you have to *add* (pure fairness can't conjure it) and musil shows the livelock
as a lasso, making the need for that assumption concrete.

## The lesson

Quorum buys you **safety** (never two leaders) for free. **Liveness** is the harder half and needs
more than a fair scheduler. It needs the randomization that breaks symmetric ties. Safety and
liveness pull on different levers; this example makes both visible in one tiny model.

Run it: `python examples/leader_election.py`
