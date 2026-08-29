"""``no_trace`` — spare musil's hot loop from line-tracing overhead.

A model check spends most of its time in the explicit-state search (hashing, enablement dispatch, apply).
Under ``pytest-cov`` (or any ``sys.settrace``-based tool) every executed line in that loop pays a tracing
cost, and nobody downstream measures musil's own line coverage — so it is pure waste. A real case: a check
that ran ~10s bare took ~120s under CI coverage and was killed, much of the amplification being coverage
tracing musil internals rather than the model logic under test.

``no_trace()`` is a context manager that pauses the current thread's trace function for its block and
restores it after. It is dependency-free (only ``sys``) and a no-op when nothing is tracing, so wrapping a
check costs nothing outside coverage/debugging runs::

    with no_trace():
        result = check(model)

It pauses ALL line tracing in the block (coverage, and any attached line-tracer), not coverage
selectively — wrap only the check, not code whose coverage you want measured. For a coarser, whole-engine
exclusion, prefer the config route in your own project instead::

    # pyproject.toml
    [tool.coverage.run]
    omit = ["*/musil/*"]     # do not measure the engine; your model code stays measured

Both target the same waste; the context manager is for a hot check inside an otherwise-measured test, the
omit for skipping the engine everywhere.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def no_trace() -> Generator[None]:
    """Pause the current thread's trace function (e.g. coverage) for the duration of the block, then
    restore it. A no-op when no trace function is installed. Pauses per-thread only (``sys.settrace``), so
    run the check on the thread you wrap."""
    saved = sys.gettrace()
    if saved is not None:
        sys.settrace(None)
    try:
        yield
    finally:
        if saved is not None:
            sys.settrace(saved)
