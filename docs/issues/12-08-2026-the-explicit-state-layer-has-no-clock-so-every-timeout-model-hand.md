---
title: The explicit-state layer has no clock, so every timeout model hand-rolls a tick counter and a horizon
status: open
area: core
owner: null
filed: 2026-08-12
scope: M
verify: test
---

Source: gitlab.com/jorgeecardona/musil issue #1 (item 3 of five), filed 2026-08-11 from adopting musil in the thalamus classifier workspace.

## MEASURED (in this repo)

- `grep -rniE "\b(tick|deadline|horizon)\b" src/` returns 0 hits. There is no clock, no tick action, and no horizon anywhere in the package.
- `sim` has a virtual clock — `Simulator.now` at [src/musil/sim.py:286-288](../../src/musil/sim.py#L286-L288), advanced by the event queue — but it belongs to the discrete-event simulator. `Model` / `Action` ([src/musil/core.py:53-90](../../src/musil/core.py#L53-L90)) have no equivalent, and nothing bridges the two.
- The existing guard against an unbounded space is `max_states` ([src/musil/core.py:152](../../src/musil/core.py#L152)), which reports `truncated=True` with `ok=True` ([src/musil/core.py:213](../../src/musil/core.py#L213)) — a *runaway* guard, not a modelling primitive. A model whose clock never stops advancing hits it and returns OK.

That last line is the sharp edge: an unbounded clock does not fail loudly. It returns
`Result(ok=True, truncated=True)`, and `__str__` renders `OK — N states, no violations (TRUNCATED at
cap)`. A reader who checks `if result:` sees success.

## REPORTED (from the adopting workspace, not verifiable here)

Two models need a timeout: a sweep that waits with a deadline, and a gateway-timeout retry ladder.
Each hand-rolls its own bounded tick action plus a horizon guard, and each hand-rolling is an
independent chance to get the bound wrong in the direction that silently truncates.

## Done

`bounded_clock(horizon)` (or equivalent) exists, supplying the tick `Action`, the enabling guard that
stops at the horizon, and the state field it advances — so a timeout model declares its bound once
instead of open-coding it. Observation that will be true: a model built with it, given a horizon
smaller than the one its liveness property needs, produces a `Result` that says so explicitly rather
than `ok=True, truncated=True`; and the same model with an adequate horizon explores a state count
linear (not unbounded) in the horizon. Truncation reporting in `Result` distinguishes "hit the
runaway cap" from "hit the declared horizon" — they are different facts and currently share one flag.

`verify: test` — both halves are assertions on a `Result`.

## Deliberately NOT doing

- **No real time, no float time.** Ticks are integers, as in `sim` ([src/musil/sim.py:270](../../src/musil/sim.py#L270)). Dense time is a different verification regime (timed automata) and does not belong in an explicit-state checker.
- **Not making the clock implicit.** A model without a timeout should not pay a state-space dimension for one. The helper is opt-in, composed into a state the modeller declares.
- **Not touching `sim`'s clock.** The two layers stay separate; this is about `Model`/`Action` only.