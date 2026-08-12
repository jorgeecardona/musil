# docs/issues — follow-ups with an owner-shaped edge

One file per follow-up, self-contained, with YAML front matter. This folder is for work that is
**known, scoped, and not being done right now** — the residue a session leaves behind when it lands
its main change. Without a home, that residue lives in a chat log nobody re-reads, and "we should
fix X" decays into nobody having ever owned X.

**The files are the store.** No database, no second copy — an issue is markdown in git, readable and
editable by hand. Everything derived (the index below above all) is *generated from* the files and
is never authoritative. A duplicate store is a fault dimension; the way to avoid one is not to
create it.

## The rules that make one worth writing

1. **Answerable cold.** Assume the reader has none of the author's context and no access to the
   session that found it. Concrete instances, file:line, the actual commands.
2. **Say what is MEASURED and what is INFERRED.** Separately, and in those words. An issue that
   states an inference as a finding sends the next person to fix the wrong thing, and they will
   believe you because you wrote it down.
3. **Define done.** Not "improve X" — the specific observation that will be true afterwards, and
   how to make it. `verify:` says which kind of evidence closes it, because they are different
   claims: `test` (a red-then-green test is enough), `probe` (only sensing the real thing counts),
   `inspect` (the artifact itself is the evidence).
4. **Name what you deliberately did NOT do,** with the reason. Silence reads as an oversight and
   gets re-litigated.
5. **Close by marking it done,** with `fixed_in:` naming the sha that landed the fix. A register
   that cannot say what fixed something has stopped being evidence.

## The format

```yaml
---
title: One line — the finding, not the fix
status: open          # open | in-progress (name an owner) | blocked | done (needs fixed_in)
scope: M              # XS | S | M | L | ?
owner: null           # a handle, or null when unowned
filed: 2026-08-03     # when it was filed; it never changes
area: core
verify: probe         # test | probe | inspect — see rule 3
blocked_by: null      # slug(s) of issues that must close first
fixed_in: null        # the sha on the mainline; required once status is done
---
```

**`blocked_by` is what makes the board honest.** `status: blocked` names a *person* who can unblock
something; `blocked_by` names the *work* it waits on. Only the second can be computed, which is why
"what can I pick up cold right now" is answerable at all.

**Naming:** `DD-MM-YYYY-short-kebab-summary.md` — the date it was filed, then a slug.

## Tooling — the folder checks itself

Managed by `cabildo issues`. The CLI, the `issues` MCP server, and any pre-commit gate are one
module, so the tool an agent calls and the gate that grades it cannot disagree.
`docs/issues/config.toml` holds this folder's specifics.

```bash
cabildo issues                # what's ready, what's yours, what everything else waits on
cabildo issues check          # the invariants; non-zero on problems
cabildo issues reindex        # regenerate the index below
cabildo issues show <slug>
```

## Open now

<!-- BEGIN GENERATED INDEX — `cabildo issues reindex` -->
| Issue | Area | Scope | Verify | Status | Waiting on |
|---|---|---|---|---|---|
| [check holds every state in RAM, so the reachable space must fit in memory](12-08-2026-check-holds-every-state-in-ram-so-the-reachable-space-must-fit.md) | core | M | inspect | open | — |
| [Decide whether musil takes an optional Hypothesis dependency before building a strategy bridge](12-08-2026-decide-whether-musil-takes-an-optional-hypothesis-dependency-before-building-a-strategy.md) | core | M | inspect | open | — |
| [Only three fixed liveness forms; no way to state an arbitrary temporal property](12-08-2026-only-three-fixed-liveness-forms-no-way-to-state-an-arbitrary-temporal.md) | liveness | L | test | open | — |
| [A green check cannot say whether an action was ever enabled or an invariant ever exercised](12-08-2026-a-green-check-cannot-say-whether-an-action-was-ever-enabled-or.md) | metrics | S | test | in-progress · @sleek-ultron-08f00 | — |
| [Decide whether probabilistic (DTMC/MDP) checking belongs in musil at all](12-08-2026-decide-whether-probabilistic-dtmc-mdp-checking-belongs-in-musil-at-all.md) | metrics | L | inspect | open | — |

_5 open — 4 open, 1 in-progress; 4 done. Generated; edit the files, then `cabildo issues reindex`._
<!-- END GENERATED INDEX -->
