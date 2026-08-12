---
title: check holds every state in RAM, so the reachable space must fit in memory
status: open
area: core
owner: null
filed: 2026-08-12
scope: M
verify: inspect
---

Source: gitlab.com/jorgeecardona/musil issue #2 (item 4 of four), filed 2026-08-12. Ranked last there and last here.

## MEASURED (in this repo)

- `check` keeps `seen: set[S]` of whole states plus `parent: dict[S, tuple[S, str] | None]` for trace reconstruction ([src/musil/core.py:172-173](../../src/musil/core.py#L172-L173)), and `explore` keeps `seen: dict[S, list[tuple[str, S]]]` — every state *and* its out-edges ([src/musil/core.py:270](../../src/musil/core.py#L270)). Memory is O(states + transitions) in full Python objects.
- The only bound today is `max_states`, default 1,000,000 ([src/musil/core.py:152](../../src/musil/core.py#L152)), which reports `truncated=True` with `ok=True` ([src/musil/core.py:213](../../src/musil/core.py#L213)).

So the constraint is real: past roughly a million frozen-dataclass states the process is the limit, and hitting the cap yields a green result that proved nothing.

## Why it is ranked last anyway

The upstream proposal is SPIN-style bitstate/hash-compaction: store `hash(state)` instead of the state, accept a quantified miss probability. Two problems with that as the *next* thing:

1. **It makes the answer approximate, and musil's whole claim is exhaustiveness.** A passing bitstate run is evidence, not proof. That is a legitimate mode, but it is a second kind of result that every docstring saying "every reachable state" would need to be qualified against — and the register already carries one deferred decision of that shape ([[12-08-2026-decide-whether-probabilistic-dtmc-mdp-checking-belongs-in-musil-at-all]]).
2. **It also breaks the counterexample.** `parent` maps state → predecessor; with only hashes stored there is nothing to reconstruct a trace from. `Result.trace` is the thing that makes a musil failure actionable, and a mode that returns "violated, no trace" is a large ergonomic step backwards. INFERRED, not measured: this is a design consequence, not something observed running.

INFERRED and worth stating: the cheaper answers to the same pressure are exact and already partly in hand — symmetry reduction now has constructions to derive it ([[12-08-2026-symmetry-reduction-can-be-validated-but-not-derived-no-way-to-explore]], landed), and partial-order reduction is the documented next lever (REDUCTION_NOTES.md). Both shrink the space without weakening the claim. Bitstate is what you reach for when those are exhausted, and there is no measurement in this repo showing they are.

## Done

Either a recorded decision that bitstate is not wanted and why, or — if it is built — `check(..., bitstate=True, hash_bits=...)` that reports an estimated coverage/collision figure and renders its result in a form that cannot be mistaken for a proof, with the trace limitation stated in the docstring rather than discovered.

Before either: a measurement. A real model that exhausts memory under symmetry reduction, named, with its state count. Without one this is a feature for a problem nobody in this repo has hit.

`verify: inspect`.

## Deliberately NOT doing

- **Not building it now.** No measured instance of the problem exists here.
- **Not raising `max_states`.** The cap is a runaway guard, not a memory strategy; raising it just moves where the process dies.