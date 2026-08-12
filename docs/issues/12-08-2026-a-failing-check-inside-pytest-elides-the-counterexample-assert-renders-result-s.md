---
title: "A failing check inside pytest elides the counterexample: assert renders Result's repr, not its trace"
status: in-progress
area: core
owner: sleek-ultron-08f00
filed: 2026-08-12
scope: XS
verify: test
---

Source: gitlab.com/jorgeecardona/musil issue #1 (item 5 of five), filed 2026-08-11 from adopting musil in the thalamus classifier workspace.

## MEASURED (reproduced in this repo, 2026-08-12)

`Result.__str__` renders the trace via `format_trace` ([src/musil/core.py:125-135](../../src/musil/core.py#L125-L135)), but `assert check(m)` in pytest shows the **repr**, and pytest shortens a long repr by eliding its middle. A five-step model with a `below-3` invariant:

```
E       AssertionError: assert Result(ok=False, states_explored=4, kind='invariant', invariant='below-3',
E       reason=None, trace=(Step(action='<init>', s...Step(action='inc', state=S(n=1)),
E       Step(action='inc', state=S(n=2)), Step(action='inc', state=S(n=3))), truncated=False)
E        +  where Result(...) = check(Model(init=S(n=0), actions=[Action(name='inc',
E       enabled=<function <lambda> at 0x7f6b651c34c0>, apply=<function <lambda>...2520>)], ...))
```

Three separate losses, all visible above: the initial state is cut (`Step(action='<init>', s...`),
the whole `Model` repr is dumped as assertion context including lambda addresses, and the counterexample
that *is* present is a raw tuple of `Step` objects rather than the `Init: … → action: …` rendering
`format_trace` already produces. The information is not merely ugly — the elision removes part of it.

The same trace through `print(result)`:

```
INVARIANT VIOLATED: below-3
  Init: S(n=0)
  → inc: S(n=1)
  → inc: S(n=2)
  → inc: S(n=3)
(4 states explored)
```

## Done

An assertion helper — `assert_ok(result)` or equivalent — that raises `AssertionError(str(result))`,
so the failure message is the `format_trace` rendering above and nothing else. Observation that will
be true: a deliberately-failing test using the helper shows the full `Init:`/`→` trace in pytest
output with no `...` elision and no `Model` repr, and a passing one is silent. Verified by capturing
pytest's own output (`pytester` or a subprocess), not by asserting on the exception in isolation —
the claim is about what the test *runner* prints.

`verify: test`.

## Deliberately NOT doing

- **No pytest plugin, no entry point, no `to_dot` artifact writing** — both are in the upstream issue and both are dropped here. A plugin means a `pytest11` entry point in [pyproject.toml](../../pyproject.toml), which makes pytest a packaging-level concern of a package whose headline property is `dependencies = []` ([pyproject.toml:32](../../pyproject.toml#L32)). A plain function that raises `AssertionError` needs no pytest at all, works under `unittest` and bare `assert`, and recovers the elided trace — which is the entire measured defect. If graph-artifact-on-failure is wanted later it is a separate issue with its own justification.
- **Not changing `Result.__repr__`.** Overriding the dataclass repr to return the pretty form would fix the pytest output for free, but reprs are debugger and log surface too, and a multi-line repr breaks the one-value-per-line assumption everything else makes. The helper is the narrower change.