"""``check_cached`` — content-addressed verdict caching, so an unchanged model is not re-checked.

Verification is expensive and pure: the verdict is a function of the model and the check options. In CI
an unchanged model is re-checked on every pipeline run — a ~5-20s exhaustive check that has not changed
since it last passed. ``check_cached`` stores the verdict on disk keyed by a stable digest and, on a hit,
returns it and skips the search. Same content-addressing a build system uses, applied to proofs
([issue #10](https://gitlab.com/jorgeecardona/musil/-/work_items/10)).

The digest cannot be computed from the model alone: actions, invariants and ``terminal`` are opaque
Python callables, and a function's ``repr`` carries its address (different every run), so hashing it would
defeat every cache hit. So the identity of the model's LOGIC is a required ``version`` string the caller
bumps whenever an action/invariant/guard BODY changes — the one soundness obligation, and it is the
caller's, exactly as the issue frames it. On top of that the digest folds in the parts that CAN be read
stably — the action and invariant NAMES, the initial states' ``repr``, the check options, and which opaque
hooks are present (``actions_fn``/``footprint``/``canonicalize``/``key``) — so a structural edit
invalidates the cache automatically even if ``version`` is not bumped. What it cannot see is a changed
lambda body under an unchanged name; that is what ``version`` is for.

The cache is a directory of pickle files, so it holds the FULL ``Result`` including a counterexample trace
over live state objects. Pickle means: load only a cache you produced (a CI workspace you control), and
the state classes must be importable at load time (module-level, as they are in real use). Writing is
best-effort — a read-only cache dir degrades to just running the check, never an error.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import cast

from musil.core import Model, Result, check

__all__ = [
    "check_cached",
    "clear_verdict_cache",
]

DEFAULT_CACHE_DIR = ".musil-cache"


def _digest[S: Hashable](
    model: Model[S],
    *,
    version: str,
    max_states: int,
    canonicalize: object,
    key: object,
) -> str:
    """A stable hex digest of everything the verdict depends on that can be read without executing an
    opaque callable: the caller's ``version``, the options, the action/invariant names, the initial
    states' repr, and which opaque hooks are present. Function reprs are deliberately excluded (their
    addresses vary per run and would make every lookup miss)."""
    payload = {
        "version": version,
        "max_states": max_states,
        "invariants": sorted(model.invariants),
        "actions": [a.name for a in model.actions],
        "init": [repr(s) for s in model.initial_states()],
        "has_actions_fn": model.actions_fn is not None,
        "has_footprint": model.footprint is not None,
        "has_canonicalize": canonicalize is not None,
        "has_key": key is not None,
    }
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def check_cached[S: Hashable](
    model: Model[S],
    *,
    version: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    max_states: int = 1_000_000,
    canonicalize: Callable[[S], S] | None = None,
    key: Callable[[S], Hashable] | None = None,
) -> Result[S]:
    """Like ``check``, but return a cached verdict when the model (identified by ``version`` plus its
    readable structure) and the options are unchanged; otherwise run ``check``, store the ``Result``, and
    return it. ``version`` is REQUIRED: bump it whenever an action/invariant/guard BODY changes, since those
    callables are opaque (see the module docstring for the full contract). ``canonicalize``/``key`` behave
    as in ``check``; changing one of THEM is a logic change too, so bump ``version`` for it as well.

    Writing the cache is best-effort: a directory that cannot be created or written just means the check
    runs (and returns) normally, never an error."""
    digest = _digest(model, version=version, max_states=max_states, canonicalize=canonicalize, key=key)
    path = Path(cache_dir) / f"{digest}.pkl"
    if path.is_file():
        try:
            # pickle.load: a local cache the caller produced (see the module docstring's trust note).
            with path.open("rb") as f:
                return cast("Result[S]", pickle.load(f))
        except (OSError, pickle.UnpicklingError, AttributeError, EOFError):
            pass  # a corrupt/stale-format entry: fall through and recompute
    result = check(model, max_states=max_states, canonicalize=canonicalize, key=key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(result, f)
    except OSError:
        pass  # best-effort: a read-only cache dir must not fail the check
    return result


def clear_verdict_cache(cache_dir: str | Path = DEFAULT_CACHE_DIR) -> int:
    """Delete every cached verdict under ``cache_dir`` and return how many files were removed. A missing
    directory is fine (returns 0). Use it to invalidate everything when a global change (a musil upgrade,
    a shared helper) makes bumping every model's ``version`` impractical."""
    directory = Path(cache_dir)
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.glob("*.pkl"):
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass
    return removed
