"""``no_trace`` — pause the current thread's trace function around a block."""

from __future__ import annotations

import sys
from types import FrameType

from musil import no_trace


def _tracer(frame: FrameType, event: str, arg: object) -> None:
    return None  # a global trace hook is enough; sys.gettrace() returns this object


def test_no_trace_pauses_and_restores_an_active_tracer():
    original = sys.gettrace()
    sys.settrace(_tracer)
    try:
        assert sys.gettrace() is _tracer
        with no_trace():
            assert sys.gettrace() is None  # paused inside the block
        assert sys.gettrace() is _tracer  # restored after
    finally:
        sys.settrace(original)


def test_no_trace_is_a_noop_when_nothing_is_tracing():
    original = sys.gettrace()
    sys.settrace(None)
    try:
        with no_trace():
            assert sys.gettrace() is None
        assert sys.gettrace() is None
    finally:
        sys.settrace(original)


def test_no_trace_restores_even_if_the_block_raises():
    original = sys.gettrace()
    sys.settrace(_tracer)
    try:
        try:
            with no_trace():
                raise ValueError("boom")
        except ValueError:
            pass
        assert sys.gettrace() is _tracer  # restored despite the exception
    finally:
        sys.settrace(original)
