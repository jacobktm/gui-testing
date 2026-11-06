"""Power/graphics state persistence helpers (system76-power specific).

Small JSON documents describing the original graphics mode, the
switchable-graphics capability, and the graphics-transition chain chosen for
the current run, so reboot-aware tests can resume from a known state.
Graphics-mode semantics are specific to ``system76-power``, so this lives in
the application package rather than the generic harness.  Previously these
helpers lived on the ``System76Power`` handler; the handler now only wraps the
``system76-power`` CLI tool and this module owns the state files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.artifacts.manifest import durable_write_text

STATE_DIR = Path.home() / ".local" / "share" / "gui-testing"
SWITCHABLE_STATE_PATH = STATE_DIR / "switchable.json"
GRAPHICS_MODE_STATE_PATH = STATE_DIR / "graphics_mode.json"
GRAPHICS_CHAIN_STATE_PATH = STATE_DIR / "graphics_chain.json"


def save_switchable_state(result: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"result": result}
    try:
        durable_write_text(SWITCHABLE_STATE_PATH, json.dumps(payload))
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


def save_graphics_chain(chain: list[tuple[str, str]]) -> None:
    """Persist the transition order chosen for the current multi-boot run.

    A resumed boot must keep walking the *same* chain (re-rotating mid-run
    would leave the in-progress rebooting edge mid-chain, where a later mode
    switch would destroy the very state it is meant to verify).
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"chain": [[source, target] for source, target in chain]}
    try:
        durable_write_text(GRAPHICS_CHAIN_STATE_PATH, json.dumps(payload))
    except Exception:
        pass


def load_graphics_chain() -> list[tuple[str, str]] | None:
    try:
        if not GRAPHICS_CHAIN_STATE_PATH.exists():
            return None
        data = json.loads(GRAPHICS_CHAIN_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            chain = data.get("chain")
            if (
                isinstance(chain, list)
                and chain
                and all(isinstance(e, list) and len(e) == 2 for e in chain)
            ):
                return [(str(source), str(target)) for source, target in chain]
    except Exception:
        pass
    return None


def save_original_graphics_mode(mode: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"mode": mode}
    try:
        durable_write_text(GRAPHICS_MODE_STATE_PATH, json.dumps(payload))
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
    """Switch graphics mode back to the original one recorded before tests.

    Returns True when a switch was actually issued — the new mode only takes
    effect after a reboot, so the caller is responsible for rebooting.  A
    ``False`` return means nothing to do (no record, already in the original
    mode, or the switch raised).

    (The old guard checked ``set_graphics``, a method the handler never had,
    making this a guaranteed no-op.)
    """
    mode = load_original_graphics_mode()
    if not mode:
        return False
    try:
        current = handler.get_graphics_mode()
        if current == mode:
            clear_original_graphics_mode()
            return False
        if hasattr(handler, "switch_graphics_mode"):
            handler.switch_graphics_mode(mode)
            clear_original_graphics_mode()
            return True
    except Exception:
        pass
    return False
