"""System76Power workflow state: switchable-graphics capability and original
graphics mode persistence.

These are handler-specific (they talk to ``system76-power``), so they belong
next to the workflows rather than in the generic harness or the handler class
itself.  The handler only wraps the CLI tool; this module owns the state files.

State is persisted to files under ``~/.local/share/gui-testing/`` so it
survives reboot-aware test runs (cleanup may run in a different process than
setup).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".local" / "share" / "gui-testing"
SWITCHABLE_STATE_PATH = STATE_DIR / "switchable.json"
ORIGINAL_MODE_PATH = STATE_DIR / "graphics_mode.json"


def _write_state(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except Exception:
        pass


def _read_state(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return None


# --- switchable graphics -----------------------------------------------------

def save_switchable_state(result: str) -> None:
    """Persist the switchable graphics result so other tests don't re-query."""
    _write_state(SWITCHABLE_STATE_PATH, {"switchable": result})


def load_switchable_state() -> str | None:
    """Load the persisted switchable graphics result, or None if not saved."""
    return (_read_state(SWITCHABLE_STATE_PATH) or {}).get("switchable")


# --- original graphics mode ---------------------------------------------------

def save_original_graphics_mode_from(handler: Any) -> None:
    """Query the handler for the current mode and persist it.

    For cleanup restore: if tests changed the graphics mode, the original one
    is restored at the end of the run.  The file survives reboots so cleanup
    (in a different process) still knows the original mode.
    """
    try:
        mode = handler.get_graphics_mode()
        if mode is not None:
            _write_state(ORIGINAL_MODE_PATH, {"mode": mode})
            print(f"[orig_graphics] original mode saved: {mode}", flush=True)
    except Exception as e:
        print(f"[orig_graphics] save failed: {e}", flush=True)


def restore_original_graphics_mode(handler: Any) -> bool:
    """Restore the graphics mode saved by save_original_graphics_mode_from.

    Returns True if the mode was changed (reboot needed to apply).  Clears
    the persisted mode afterwards so it isn't restored twice.
    """
    import subprocess
    try:
        original = (_read_state(ORIGINAL_MODE_PATH) or {}).get("mode")
        if original is None:
            return False
        current = None
        try:
            # Kill any stuck system76-power processes first
            subprocess.run(["pkill", "-9", "-f", "system76-power"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "-n", "systemctl", "restart", "com.system76.PowerDaemon.service"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            current = handler.get_graphics_mode()
        except Exception as e:
            print(f"[restore_graphics] get mode failed: {e}", flush=True)
            current = None
        if current == original:
            ORIGINAL_MODE_PATH.unlink(missing_ok=True)
            return False
        try:
            r = subprocess.run(["system76-power", "graphics", original], check=False, timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ORIGINAL_MODE_PATH.unlink(missing_ok=True)
            return True
        except subprocess.TimeoutExpired:
            print("[restore_graphics] timed out, proceeding to reboot", flush=True)
            ORIGINAL_MODE_PATH.unlink(missing_ok=True)
            return True
        except Exception as e:
            print(f"[restore_graphics] failed: {e}", flush=True)
            ORIGINAL_MODE_PATH.unlink(missing_ok=True)
            return True
    except Exception as e:
        print(f"[restore_graphics] failed: {e}", flush=True)
    return False
