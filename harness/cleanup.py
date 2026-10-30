"""Generic cleanup registry for harness/handlers/workflows.

Allows components to register cleanup functions without test-specific
logic in general code paths.
"""

from __future__ import annotations

import atexit
import threading
from typing import Callable

_lock = threading.Lock()
_cleanups: list[Callable[[], None]] = []
_registered = False


def register_cleanup(fn: Callable[[], None]) -> None:
    global _registered
    with _lock:
        _cleanups.append(fn)
        if not _registered:
            atexit.register(_run_all)
            _registered = True


def run_all() -> None:
    _run_all()


def _run_all() -> None:
    with _lock:
        fns = list(_cleanups)
        _cleanups.clear()
    for fn in fns:
        try:
            fn()
        except Exception:
            pass
