---
title: conformance.replay and RefinementMonitor are sync-only, so an async implementation cannot be driven
status: open
area: conformance
owner: null
filed: 2026-08-12
scope: S
verify: test
---

Source: gitlab.com/jorgeecardona/musil issue #1, filed 2026-08-11 from adopting musil in the thalamus classifier workspace. This is item 1 of five; the others are filed separately.

## MEASURED (in this repo)

- `replay` takes `step_fn: Callable[[R, str], R]` — [src/musil/conformance.py:118-129](../../src/musil/conformance.py#L118-L129) — and calls it synchronously at [src/musil/conformance.py:144](../../src/musil/conformance.py#L144).
- `RefinementMonitor.observe` is sync — [src/musil/refine.py:92](../../src/musil/refine.py#L92) — and `check_refinement` consumes a sync `Iterable[C]` at [src/musil/refine.py:112-131](../../src/musil/refine.py#L112-L131).
- `grep -rn "async \|await \|asyncio" src/` returns 0 hits. There is no async surface anywhere in the package.

## REPORTED (from the adopting workspace, not verifiable here)

The implementation under check is async (Litestar handlers, an async HTTP client). The only way to
drive it through `replay` today is `asyncio.run(...)` inside `step_fn`, once per step. That is
unusable inside an already-running loop (`asyncio.run` raises `RuntimeError: cannot be called from a
running event loop`, so any `async def test_` is out) and it destroys loop-scoped state between
steps — a connection pool or an open transaction created in step *k*'s loop is dead in step *k+1*'s.

## Done

`areplay(...)` exists with the same signature as `replay` except `step_fn: Callable[[R, str], Awaitable[R]]`
and `project: Callable[[R], S] | Callable[[R], Awaitable[S]]`, returning `ConformanceResult`; and
`RefinementMonitor` has an `aobserve` plus an `acheck_refinement` over an `AsyncIterable[C]`.
Observation that will be true: a test that is itself `async def`, driving a step function that keeps
one `aiohttp`/`httpx` client alive across all steps of a trace, returns `ok=True` — and returns the
same `Divergence` (same `trace_index`, `step_index`, `action`) as the sync `replay` when pointed at a
deliberately-wrong step function. Both paths share the comparison logic rather than duplicating it.

`verify: test` — a red-then-green test is the whole claim. There is no real async system in this
repo to probe; a fake async step_fn exercises the same control flow.

## Deliberately NOT doing

- **No async in `check`/`explore`.** Actions are pure and in-process by contract
  ([src/musil/core.py:53-62](../../src/musil/core.py#L53-L62)); making the sweep async would invite I/O
  inside `apply`, which breaks the determinism the whole checker rests on. Async belongs only at the
  boundary that touches the real system: conformance and refinement.
- **No dependency.** `asyncio` is stdlib, so `dependencies = []`
  ([pyproject.toml:32](../../pyproject.toml#L32)) is unaffected.
- **Not deleting or wrapping the sync path.** Sync `replay` stays the primary API; `areplay` is a
  sibling. Implementing sync-on-top-of-async would force an event loop on callers who have none.