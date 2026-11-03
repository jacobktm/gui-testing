"""Power/graphics state persistence helpers.

These are workflow-level concerns: persisting small JSON documents describing
the original graphics mode and the switchable-graphics capability so that
reboot-aware tests can resume from a known state.  Previously these helper
methods lived on the ``System76Power`` handler; the handler now only wraps the
``system76-power`` CLI tool and this module owns the state files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / ".local" / "share" / "gui-testing"
SWITCHABLE_STATE_PATH = STATE_DIR / "switchable.json"
GRAPHICS_MODE_STATE_PATH = STATE_DIR / "graphics_mode.json"


def save_switchable_state(result: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"result": result}
    try:
        SWITCHABLE_STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def load_switchable_state() -> str | None:
    try:
        if not SWITCHABLE_STATE_PATH.exists():
            return None
        data = json.loads(SWITCHABLE_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            result = data.get("result")
            return result if isinstance(result, str) else None
    except Exception:
        pass
    return None


def save_original_graphics_mode(mode: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode}
    try:
        GRAPHICS_MODE_STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except Exception:
        pass


def load_original_graphics_mode() -> str | None:
    try:
        if not GRAPHICS_MODE_STATE_PATH.exists():
            return None
        data = json.loads(GRAPHICS_MODE_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            mode = data.get("mode")
            return mode if isinstance(mode, str) else None
    except Exception:
        pass
    return None


def save_original_graphics_mode_from(handler: Any) -> None:
    try:
        mode = handler.get_graphics_mode()
        if isinstance(mode, str) and mode:
            save_original_graphics_mode(mode)
    except Exception:
        pass


def clear_original_graphics_mode() -> None:
    try:
        if GRAPHICS_MODE_STATE_PATH.exists():
            GRAPHICS_MODE_STATE_PATH.unlink()
    except Exception:
        pass


def restore_original_graphics_mode(handler: Any) -> bool:
    mode = load_original_graphics_mode()
    if not mode:
        return False
    try:
        if hasattr(handler, "set_graphics"):
            handler.set_graphics(mode)
            clear_original_graphics_mode()
            return True
    except Exception:
        pass
    return False
