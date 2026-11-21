# AGENTS.md

Guidance for AI coding agents working in this repo. Humans: read README.md (usage) and CHANGELOG.md.

## Overview

musil is a dependency-free, explicit-state model checker for Python 3.12+. You describe a system
as frozen-dataclass states, `Action`s (guarded transitions), and invariants; `check()` exhausts
every reachable state in every concurrent interleaving (concurrency by interleaving) and returns
the shortest counterexample, or confirms none exists. Beyond safety it covers deadlock, liveness
(weak/strong fairness, response properties), composition of components, channel modelling, symmetry
reduction, deterministic simulation testing, and open-system checking against adversarial
environments. Zero runtime dependencies; the whole library lives under `src/musil/`.

Key modules: `core.py` (Model, Action, check, explore, Result), `graph.py` (Graphviz DOT output),
`liveness.py`
(check_liveness, LivenessResult), `sim.py` (simulate, deterministic simulation testing),
`compose.py`, `channels.py`, `symmetry.py`, `conformance.py`, `environments/`, `faults.py`.

## Build

- Toolchain (moon + uv) is pinned in `.prototools`; `proto install` brings it up.
- `uv sync` installs dependencies (`uv sync --extra docs` also pulls the docs stack).
- `make install-hooks` once, to enable the tracked git hooks (`.githooks/`: pre-commit auto-bump +
  pre-push checks).
- `make build` builds the sdist and wheel into `dist/` (via `uv build`).

## Test

- `make test` runs the suite (`uv run pytest -q`).
- `make check` runs lint + typecheck + test. Everything in it must pass before you commit.
- `moon run :ci` runs the full CI graph (lint, typecheck, test, build, docs, version-guard) in one
  task order; this is what CI runs. On `main`, `moon run :release` also runs and publishes to PyPI.
- `make docs` builds the docs strictly (`uv run --extra docs mkdocs build --strict`), as CI does.
  CI publishes the site to GitLab Pages. It is in `:ci` but not in the local `make check` gate.

## Style

- Format and autofix: `make format` (ruff format + ruff check --fix, line length 100).
- Lint: `make lint` (ruff, `select = ["E","F","W","I","B","UP","SIM","RUF"]`). Types: `make
  typecheck` (pyright, strict, on `src`, `tests`, `examples`).
- Prefer frozen dataclasses and explicit types; keep the public API typed (`py.typed`). The top
  level (`src/musil/__init__.py`, `__all__`) exports the core names only (34). Every other public
  name is imported from its submodule, for example `musil.induction.check_inductive`. Add a new
  public name to its submodule's `__all__`. The `_MOVED` table in `__init__.py` is a deprecated
  shim for the pre-0.35 flat imports: do not add to it.
- The package is zero-dependency by design. Do not add anything to `[project.dependencies]`;
  dev/test deps go in `[dependency-groups] dev`, docs deps in `[project.optional-dependencies]
  docs`.

## Gotchas

- Version: the `__version__` literal in `src/musil/__init__.py`, which hatchling reads so
  `pyproject.toml` never disagrees. Do not edit it by hand: the pre-commit hook auto-bumps it when
  anything under `src/` changes, and CI's version-guard enforces that a `src/` change carries a
  bump. For a deliberate minor/major bump run `make bump TYPE=minor` (or `major`).
- Merging a version bump to `main` releases itself: a green `main` pipeline publishes to PyPI
  via OIDC when that version is not yet published (no-op otherwise). There is no tag step.
- `format-check` is intentionally NOT in the `:ci` gate yet (the tree is not ruff-format-clean),
  so avoid reformatting unrelated files in a change. `make format` autofixes; `format-check` is the
  read-only CI variant.
- States must be hashable and frozen. The BFS explorer stores every visited state in a set. Use
  `@dataclass(frozen=True)` (or named tuples). A mutable state silently breaks the checker.
- Python 3.12+ only. Don't add compatibility shims for earlier versions.
- Record follow-ups in `docs/issues/` (tracked markdown), not as scattered TODO comments.
- `.mcp.json` is local agent wiring and is gitignored; do not commit it.
