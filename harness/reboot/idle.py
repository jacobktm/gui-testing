"""Disable idle/lock/suspend behavior during tests and restore it afterwards.

Each desktop gets its own backend, and only the backend for the *detected*
desktop is ever used.  This matters because GNOME tools such as ``gsettings``
are not meaningful (or even installed) on COSMIC systems, and COSMIC config
files are meaningless on Ubuntu.

Backends
--------
``gnome``
    ``gsettings`` keys under ``org.gnome.desktop.session``,
    ``org.gnome.desktop.screensaver``, ``org.gnome.desktop.lockdown`` and
    ``org.gnome.settings-daemon.plugins.power``.  Every key is read first;
    keys that do not exist on this GNOME version (for example Ubuntu-only
    keys) are skipped rather than assumed.  A ``gnome-session-inhibit``
    process additionally inhibits idle at the session level as a fallback.

``cosmic``
    ``cosmic-idle`` reads its settings from ``cosmic-config``:

    * application ``com.system76.CosmicIdle``
    * version ``1``
    * keys ``screen_off_time``, ``suspend_on_battery_time``,
      ``suspend_on_ac_time`` (``Option<u32>`` milliseconds, serialized as RON)

    Writing ``None`` disables the timeout.  Each key is a separate file under
    ``~/.config/cosmic/com.system76.CosmicIdle/v1/``; cleanup restores the
    original contents, or deletes files that did not exist before.

State is persisted to ``~/.local/share/gui-testing/idle_state.json`` so it
survives a reboot (reboot tests resume the suite on the next boot).  Saving is
idempotent: the first save wins, so a resumed run re-disables the timer
without overwriting the user's original values.

Every function is best-effort and never raises; failures are logged so a
missing tool or schema does not abort a test run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "share" / "gui-testing"
IDLE_STATE_PATH = STATE_DIR / "idle_state.json"

_MISSING = "__MISSING__"

# ---- GNOME -----------------------------------------------------------------

# (schema, key, value to apply while testing)
GNOME_KEYS: list[tuple[str, str, str]] = [
    ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
    ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
    ("org.gnome.desktop.screensaver", "lock-delay", "uint32 0"),
    # Removed in newer GNOME releases; skipped when absent.
    ("org.gnome.desktop.screensaver", "idle-activation-enabled", "false"),
    # Ubuntu-only, skipped when absent.
    ("org.gnome.desktop.screensaver", "ubuntu-lock-on-suspend", "false"),
    # Belt and braces: disables screen locking outright.
    ("org.gnome.desktop.lockdown", "disable-lock-screen", "true"),
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type", "'nothing'"),
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-type", "'nothing'"),
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout", "0"),
    ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "0"),
    ("org.gnome.settings-daemon.plugins.power", "idle-dim", "false"),
]

# ---- COSMIC ----------------------------------------------------------------

COSMIC_IDLE_APP = "com.system76.CosmicIdle"
COSMIC_IDLE_VERSION = "v1"
COSMIC_IDLE_KEYS = (
    "screen_off_time",
    "suspend_on_battery_time",
    "suspend_on_ac_time",
)


def _log(message: str) -> None:
    print(f"[idle] {message}", file=sys.stderr, flush=True)


def _run(cmd: list[str], timeout: float = 10.0):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None


def _desktop_kind() -> str | None:
    """Return ``"gnome"``, ``"cosmic"`` or ``None`` for the current session.

    Environment variables win because they describe the session the tests
    actually run in; the display-manager heuristics are only a fallback.
    """
    joined = " ".join(
        os.environ.get(key, "")
        for key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
    ).lower()
    if "cosmic" in joined:
        return "cosmic"
    if "gnome" in joined or "ubuntu" in joined or "pop" in joined:
        return "gnome"
    try:
        from .session import detect_desktop

        detected = detect_desktop()
        if detected in ("gnome", "cosmic"):
            return detected
    except Exception:
        pass
    return None


def _gsettings_available() -> bool:
    return shutil.which("gsettings") is not None


def _gsettings_get(schema: str, key: str) -> str | None:
    result = _run(["gsettings", "get", schema, key])
    if result is not None and result.returncode == 0:
        return result.stdout.strip()
    return None


def _gsettings_set(schema: str, key: str, value: str) -> bool:
    result = _run(["gsettings", "set", schema, key, value])
    if result is None:
        return False
    if result.returncode != 0:
        _log(f"gsettings set {schema} {key} failed: {result.stderr.strip()}")
        return False
    return True


def _cosmic_dir() -> Path:
    return Path.home() / ".config" / "cosmic" / COSMIC_IDLE_APP / COSMIC_IDLE_VERSION


def _update_state(**changes) -> None:
    """Merge ``changes`` into the saved state (used for the inhibitor PID)."""
    state = _load_state()
    if state is None:
        return
    state.update(changes)
    _write_state(state)


def _start_gnome_inhibitor() -> int | None:
    """Belt-and-braces: inhibit idle at the GNOME session level.

    ``gsettings`` alone normally prevents blanking/locking, but a session-level
    inhibitor also covers cases where a session policy or extension overrides
    the user's settings.  Returns the process id, or ``None`` when the helper
    is unavailable or failed to start.
    """
    if shutil.which("gnome-session-inhibit") is None:
        return None
    try:
        proc = subprocess.Popen(
            [
                "gnome-session-inhibit",
                "--inhibit",
                "idle",
                "--reason",
                "gui-testing",
                "sleep",
                "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        _log(f"could not start gnome-session-inhibit: {exc}")
        return None
    _log(f"started gnome-session-inhibit (pid {proc.pid})")
    return proc.pid


def _is_our_inhibitor(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        cmdline = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except Exception:
        return False
    # PIDs are reused across reboots; only trust a process that is our helper.
    return b"gnome-session-inhibit" in cmdline and b"gui-testing" in cmdline


def _stop_inhibitor(pid: int | None) -> None:
    if not _is_our_inhibitor(pid):
        return
    try:
        os.kill(int(pid), 15)
        _log(f"stopped gnome-session-inhibit (pid {pid})")
    except Exception:
        pass


# ---- state -----------------------------------------------------------------


def _load_state() -> dict | None:
    try:
        return json.loads(IDLE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        IDLE_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        _log(f"could not save state: {exc}")


def save_idle_state() -> dict:
    """Record the current idle/lock settings.  Idempotent per boot cycle."""
    existing = _load_state()
    if existing is not None:
        return existing

    desktop = _desktop_kind()
    state: dict = {"desktop": desktop, "gsettings": {}, "cosmic": []}
    _log(f"detected desktop: {desktop}")

    if desktop == "gnome":
        if not _gsettings_available():
            _log("gsettings not found; cannot save GNOME idle settings")
        else:
            for schema, key, _ in GNOME_KEYS:
                value = _gsettings_get(schema, key)
                if value is not None:
                    state["gsettings"][f"{schema}|{key}"] = value

    elif desktop == "cosmic":
        directory = _cosmic_dir()
        for key in COSMIC_IDLE_KEYS:
            path = directory / key
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8")
                except Exception:
                    content = None
            else:
                content = _MISSING
            state["cosmic"].append({"path": str(path), "content": content})
    else:
        _log("unknown desktop; idle settings left untouched")

    _write_state(state)
    return state


def disable_idle() -> bool:
    """Disable idle blanking, screen locking and idle suspend."""
    desktop = _desktop_kind()
    if desktop is None:
        _log("unknown desktop; nothing to disable")
        return False

    if desktop == "gnome":
        if not _gsettings_available():
            _log("gsettings not found; cannot disable GNOME idle settings")
            return False
        ok = 0
        for schema, key, value in GNOME_KEYS:
            # Skip keys this GNOME version/schema does not define.
            if _gsettings_get(schema, key) is None:
                continue
            if _gsettings_set(schema, key, value):
                ok += 1
        _log(f"applied {ok} GNOME idle setting(s)")
        # Reuse an inhibitor from an earlier attempt in this run, if alive.
        pid = (_load_state() or {}).get("inhibitor_pid")
        if not _is_our_inhibitor(pid):
            pid = _start_gnome_inhibitor()
        if pid:
            _update_state(inhibitor_pid=pid)
        return ok > 0

    if desktop == "cosmic":
        directory = _cosmic_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            _log(f"could not create {directory}: {exc}")
            return False
        ok = 0
        for key in COSMIC_IDLE_KEYS:
            try:
                (directory / key).write_text("None", encoding="utf-8")
                ok += 1
            except Exception as exc:
                _log(f"could not write {key}: {exc}")
        _log(f"applied {ok} COSMIC idle setting(s)")
        return ok > 0

    return False


def restore_idle() -> bool:
    """Restore the settings saved by :func:`save_idle_state`."""
    state = _load_state()
    if state is None:
        return False

    desktop = state.get("desktop")

    # Stop the session-level idle inhibitor, if one was started.
    _stop_inhibitor(state.get("inhibitor_pid"))

    # Restore gsettings values recorded for GNOME.
    gsettings = state.get("gsettings") or {}
    if gsettings and _gsettings_available():
        restored = 0
        for entry, value in gsettings.items():
            if "|" not in entry:
                continue
            schema, key = entry.split("|", 1)
            if _gsettings_set(schema, key, value):
                restored += 1
        _log(f"restored {restored} GNOME idle setting(s)")

    # Restore COSMIC files: rewrite originals, delete files we created.
    for item in state.get("cosmic") or []:
        try:
            path = Path(item["path"])
            content = item.get("content")
            if content == _MISSING:
                if path.exists():
                    path.unlink()
            elif content is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        except Exception as exc:
            _log(f"could not restore {item.get('path')}: {exc}")

    if desktop == "cosmic" and state.get("cosmic"):
        _log("restored COSMIC idle settings")

    try:
        IDLE_STATE_PATH.unlink()
    except Exception:
        pass
    return True
