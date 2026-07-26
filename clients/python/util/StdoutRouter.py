"""A process-wide, thread-isolated stdout router.

Installed once, it replaces ``sys.stdout`` with a proxy that fans each write out
to any sinks registered *for the current thread*, then always forwards the text
to the original stream. Threads with no sink registered are unaffected, and the
forward-through means an already-installed downstream router (e.g. the web
backend's per-seat live-view capture in ``web/backend/live.py``) and the console
keep receiving output — so this can be layered in without disturbing existing
capture.

This is the shared primitive behind per-move log capture: each SDK game session
registers a sink on its own thread that tags a player's ``print()`` output with
the move being decided. Sinks are keyed by thread via ``threading.local``, so
concurrent sessions (e.g. four live-play seats) never cross-contaminate.
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, List


class _StdoutRouter:
    def __init__(self, original):
        self._original = original
        self._local = threading.local()

    def _sinks(self) -> List[Callable[[str], None]]:
        sinks = getattr(self._local, "sinks", None)
        if sinks is None:
            sinks = []
            self._local.sinks = sinks
        return sinks

    def add_sink(self, fn: Callable[[str], None]) -> Callable[[str], None]:
        self._sinks().append(fn)
        return fn

    def remove_sink(self, fn: Callable[[str], None]) -> None:
        try:
            self._sinks().remove(fn)
        except ValueError:
            pass

    def write(self, s):
        # Fan out to this thread's sinks first (a broken sink must never break
        # the program's output), then always forward downstream so the console
        # and any inner router still see it.
        for fn in list(self._sinks()):
            try:
                fn(s)
            except Exception:
                pass
        return self._original.write(s)

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        # Delegate isatty/encoding/fileno/etc. to the real stream.
        return getattr(self._original, name)


_installed: _StdoutRouter | None = None
_install_lock = threading.Lock()


def ensure_installed() -> _StdoutRouter:
    """Install the router over ``sys.stdout`` once; return the singleton."""
    global _installed
    with _install_lock:
        if _installed is None:
            _installed = _StdoutRouter(sys.stdout)
            sys.stdout = _installed
        return _installed


def add_sink(fn: Callable[[str], None]) -> Callable[[str], None]:
    """Register a per-thread stdout sink; returns the handle to remove later."""
    return ensure_installed().add_sink(fn)


def remove_sink(fn: Callable[[str], None]) -> None:
    if _installed is not None:
        _installed.remove_sink(fn)
