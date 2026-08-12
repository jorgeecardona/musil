---
title: Decide whether musil takes an optional Hypothesis dependency before building a strategy bridge
status: open
area: core
owner: null
filed: 2026-08-12
scope: M
verify: inspect
---

Source: gitlab.com/jorgeecardona/musil issue #1 (item 4 of five), filed 2026-08-11 from adopting musil in the thalamus classifier workspace. This is the one of the five that is a **decision** first and code second, which is why it is filed as `verify: inspect`.

## MEASURED (in this repo)

- `dependencies = []` — [pyproject.toml:32](../../pyproject.toml#L32) — and "dependency-free" appears in the package description ([pyproject.toml:6](../../pyproject.toml#L6)), the module docstring ([src/musil/__init__.py:1](../../src/musil/__init__.py#L1)), and the pyproject comment naming it the point of the project ([pyproject.toml:2-4](../../pyproject.toml#L2-L4)).
- Precedent for not-a-hard-dependency exists in two shapes already: `docs` is an optional extra ([pyproject.toml:34-40](../../pyproject.toml#L34-L40)), and `dev` is a dependency group carrying ruff/pyright/pytest ([pyproject.toml:58](../../pyproject.toml#L58)).
- `grep -rn "hypothesis" src/` returns 0 hits.

## REPORTED (from the adopting workspace, not verifiable here)

The guard model-checks there prove properties over one fixed fixture (8 taxonomy codes). A strategy
adapter drawing model instances — exclusion graphs, confidences, route sets — would turn one-instance
proofs into a proof per drawn instance. Drawing replay traces from `generate_traces`
([src/musil/conformance.py:93](../../src/musil/conformance.py#L93)) would additionally serve conformance
fuzzing.

## The tension, stated plainly

The value is real but it is *glue*: a user can write `@given(st.lists(...))` and call `check` inside
the test body in about fifteen lines, with no help from musil. What musil would add is a library of
instance strategies. That is a genuine convenience and also the first thing in the package that
cannot be used without installing something else. Every one of the other four items in the upstream
issue is stdlib-only; this one is not, and that is the whole reason it is ranked last here.

## Done

A decision is recorded in the repo — CHANGELOG, README, or a design note — saying either:

- **no**, with the reason, and the upstream issue answered so it is not re-proposed; or
- **yes, as an optional extra**, in which case: `hypothesis` appears under `[project.optional-dependencies]` and never under `dependencies`; `import musil` succeeds with hypothesis absent; a `musil.hypothesis` module imports it lazily and raises a message naming the extra when it is missing; and a test asserts the import-without-hypothesis path.

Observation that will be true either way: `pip install musil` in a clean environment installs zero
third-party packages, and `python -c "import musil"` works. That invariant is what the decision must
not break, whichever way it goes.

`verify: inspect` — the artifact (the recorded decision, and the pyproject if it goes ahead) is the
evidence. The import-isolation test that would follow a "yes" is part of the same change, not a
separate claim.

## Deliberately NOT doing

- **Not building the strategies before the decision.** Writing `musil/hypothesis.py` first makes the
  dependency question moot by fait accompli, which is the wrong order for the one property the
  project advertises.
- **Not proposing a vendored mini-generator.** Reimplementing shrinking to avoid a dependency is
  strictly worse than either option above.
- **Not blocking the other four items on this.** They are stdlib-only and independent; nothing here
  gates them.