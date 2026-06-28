# Vote tallying — the integrity a checker can prove, and the secrecy it can't

**What this teaches:** where model checking helps with "secure voting" and where it fundamentally doesn't. The line is sharp and worth knowing before you reach for the wrong tool.

## Two kinds of property

"Secure voting" bundles two very different things:

- **Integrity** — every eligible voter votes at most once, every cast ballot is counted exactly once, the announced tally equals the ballots cast. This is a *state machine*, and a careless concurrent tally can drop or double-count a vote. **musil checks this.**
- **Secrecy** — no one can tell how you voted; no one can coerce you. This is about what an *observer can infer*, which needs cryptography, not state enumeration. **musil cannot check this** — it has no notion of secrecy, and the example says so plainly rather than pretending otherwise.

## 1. A racy tally loses a vote

Count each ballot as read-then-write — read the running total, then write total + 1 — and two concurrent counts that both read the same total before either writes lose a vote (the classic lost update):

```
VOTE LOST — invariant 'tally-matches-counted' violated (a counted ballot vanished):
  → read:0   (reads total 0)
  → read:1   (reads total 0)
  → write:0  (total = 1)
  → write:1  (total = 1)   ← two ballots counted, total says 1
```

## 2. An atomic tally is correct

Count each ballot in one indivisible step and the invariants hold over the whole state space: only eligible voters vote, each at most once, the total always equals the ballots counted, and the final tally equals the ballots cast.

```
eligible-only, tally matches, no overcount: OK (27 states)
```

## The lesson

The countable parts of election integrity — at-most-once, exactly-once, tally-equals-ballots — are a clean model-checking target, and the bug (a dropped vote under concurrent counting) is the same lost-update race that bites shared counters everywhere. But ballot secrecy is a different universe of property; reaching for a model checker there is a category error. Knowing which half you're in is the real takeaway.

Run it: `python examples/voting_tally.py`
