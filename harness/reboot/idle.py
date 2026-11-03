"""Disable idle/lock/suspend behavior during tests and restore afterwards.

Handles:
- GNOME/Ubuntu: gsettings (org.gnome.desktop.session, org.gnome.desktop.screensaver, org.gnome.settings-daemon.plugins.power)
- COSMIC (Pop!_OS 24.04): cosmic config files in ~/.config/cosmic/* (delete overrides on cleanup)
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


STATE_DIR = Path.home() / ".local" / "share" / "gui-testing"
IDLE_STATE_PATH = STATE_DIR / "idle_state.json"


def _run(cmd: list[str], timeout: float = 10.0):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _get_desktop():
    try:
        from .session import detect_session, detect_desktop
        sess = detect_session()
        desk = detect_desktop()
        return sess, desk
    except Exception:
        return None, None


def _gsettings_get(schema: str, key: str):
    r = _run(["gsettings", "get", schema, key])
    if r and r.returncode == 0:
        return r.stdout.strip()
    return None


def _gsettings_set(schema: str, key: str, value: str):
    r = _run(["gsettings", "set", schema, key, value])
    return r is not None and r.returncode == 0


def save_idle_state() -> dict:
    state = {"desktop": None, "gsettings": {}, "cosmic": []}
    sess, desk = _get_desktop()
    if desk:
        state["desktop"] = desk.name
    if sess:
        state["session_type"] = sess.session_type
        state["desktop_env"] = sess.desktop_env

    # GNOME/gsettings
    if desk and desk.name in ("gnome", "ubuntu", "pop-gnome") or os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("gnome") >= 0:
        schemas_keys = [
            ("org.gnome.desktop.session", "idle-delay"),
            ("org.gnome.desktop.screensaver", "lock-enabled"),
            ("org.gnome.desktop.screensaver", "idle-activation-enabled"),
            ("org.gnome.desktop.screensaver", "lock-delay"),
            ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type"),
            ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type"),
            ("org.gnome.settings-daemon.plugins.power", "idle-dim"),
        ]
        for schema, key in schemas_keys:
            v = _gsettings_get(schema, key)
            if v is not None:
                state["gsettings"][(schema, key)] = v

    # COSMIC - record existing override files we'll touch
    cosmic_cfgs = [
        Path.home() / ".config" / "cosmic" / "com.system76.CosmicSession" / "v1" / "autowake",
        Path.home() / ".config" / "cosmic" / "com.system76.CosmicSession" / "v1" / "idle-timeout",
        Path.home() / ".config" / "cosmic" / "com.system76.CosmicSession" / "v1" / "suspend-timeout",
        Path.home() / ".config" / "cosmic" / "com.system76.CosmicSettingsDaemon" / "v1" / "idle-timeout",
        Path.home() / ".config" / "cosmic" / "com.system76.CosmicPowerDaemon" / "v1" / "idle-timeout",
    ]
    for p in cosmic_cfgs:
        if p.exists():
            try:
                state["cosmic"].append({"path": str(p), "content": p.read_text()})
            except Exception:
                state["cosmic"].append({"path": str(p), "content": None})
        else:
            state["cosmic"].append({"path": str(p), "content": "__MISSING__"})

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Convert tuple keys to strings for JSON
        save_state = {
            "desktop": state["desktop"],
            "session_type": state.get("session_type"),
            "desktop_env": state.get("desktop_env"),
            "gsettings": {f"{s}|{k}": v for (s, k), v in state["gsettings"].items()},
            "cosmic": state["cosmic"],
        }
        IDLE_STATE_PATH.write_text(json.dumps(save_state))
    except Exception:
        pass

    return state


def disable_idle() -> bool:
    """Disable idle/lock/suspend."""
    sess, desk = _get_desktop()
    desktop_name = desk.name if desk else ""
    desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

    success = False

    # Try gsettings for GNOME-based
    if desktop_name in ("gnome", "ubuntu", "pop-gnome") or "gnome" in desktop_env:
        try:
            _gsettings_set("org.gnome.desktop.session", "idle-delay", "uint32 0")
            _gsettings_set("org.gnome.desktop.screensaver", "lock-enabled", "false")
            _gsettings_set("org.gnome.desktop.screensaver", "idle-activation-enabled", "false")
            _gsettings_set("org.gnome.desktop.screensaver", "lock-delay", "uint32 0")
            _gsettings_set("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'")
            _gsettings_set("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "'nothing'")
            _gsettings_set("org.gnome.settings-daemon.plugins.power", "idle-dim", "false")
            success = True
        except Exception:
            pass

    # COSMIC
    if desktop_name in ("cosmic",) or "cosmic" in desktop_env:
        try:
            # Disable idle timeouts by setting to never/large values or removing
            cosmic_paths = [
                (Path.home() / ".config" / "cosmic" / "com.system76.CosmicSession" / "v1" / "idle-timeout", "0"),
                (Path.home() / ".config" / "cosmic" / "com.system76.CosmicSession" / "v1" / "suspend-timeout", "0"),
                (Path.home() / ".config" / "cosmic" / "com.system76.CosmicSettingsDaemon" / "v1" / "idle-timeout", "0"),
                (Path.home() / ".config" / "cosmic" / "com.system76.CosmicPowerDaemon" / "v1" / "idle-timeout", "0"),
            ]
            for p, val in cosmic_paths:
                try:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    # Write as plain text or appropriate format - COSMIC often uses simple formats
                    p.write_text(val)
                except Exception:
                    pass
            success = True
        except Exception:
            pass

    return success


def restore_idle() -> bool:
    """Restore idle/lock/suspend settings."""
    try:
        if not IDLE_STATE_PATH.exists():
            return False
        save_state = json.loads(IDLE_STATE_PATH.read_text())
    except Exception:
        return False

    success = False
    desktop_env = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

    # Restore gsettings
    gsettings = save_state.get("gsettings", {})
    if gsettings:
        try:
            for k, v in gsettings.items():
                if "|" in k:
                    schema, key = k.split("|", 1)
                    _gsettings_set(schema, key, v)
            success = True
        except Exception:
            pass

    # Restore COSMIC - delete created files if they didn't exist before
    for item in save_state.get("cosmic", []):
        try:
            p = Path(item["path"])
            content = item.get("content")
            if content == "__MISSING__":
                if p.exists():
                    p.unlink()
            elif content is not None:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            success = True
        except Exception:
            pass

    try:
        IDLE_STATE_PATH.unlink()
    except Exception:
        pass

    return success
