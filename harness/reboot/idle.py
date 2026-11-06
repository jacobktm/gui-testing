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
    ``org.gnome.settings-daemon.plugins.power``.  Key existence is probed with
    ``gsettings list-keys`` so an unreachable session bus is reported as a
    failure instead of looking like "every key is undefined".  Applied keys are
    read back, and the critical subset (``idle-delay``, ``lock-enabled``) is
    verified; ``tests/idle_guard.py`` asserts it again as a fail-fast guard.
    A ``gnome-session-inhibit`` process additionally inhibits idle at the
    session level as a fallback.

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
without overwriting the user's original values.  The generated resume script
re-applies the protection *before* pytest starts, covering the gap between
autologin and ``pytest_configure``.

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


# Schema -> {key: defined?}, cached.  ``gsettings get`` returns rc!=0 for BOTH
# an undefined key and an unreachable session bus; without this probe a run
# launched without DBUS_SESSION_BUS_ADDRESS would silently skip every key and
# run under the user's real idle+lock policy ("applied 0" with no clue).
_SCHEMA_KEYS: dict[str, set[str] | None] = {}


def _gsettings_list_keys(schema: str) -> set[str] | None:
    """Defined keys of *schema*, or ``None`` when gsettings cannot talk to dconf."""
    if schema in _SCHEMA_KEYS:
        return _SCHEMA_KEYS[schema]
    result = _run(["gsettings", "list-keys", schema])
    keys: set[str] | None = None
    if result is not None:
        if result.returncode == 0:
            keys = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        else:
            _log(f"gsettings list-keys {schema} rc={result.returncode}: {result.stderr.strip()}")
    _SCHEMA_KEYS[schema] = keys
    return keys


def _gsettings_key_exists(schema: str, key: str) -> bool:
    keys = _gsettings_list_keys(schema)
    return keys is not None and key in keys


def _gsettings_get2(schema: str, key: str) -> tuple[bool, str | None]:
    """``(bus_ok, value)`` — distinguishes 'read failed' from 'key absent'."""
    if not _gsettings_key_exists(schema, key):
        return True, None
    result = _run(["gsettings", "get", schema, key])
    if result is not None and result.returncode == 0:
        return True, result.stdout.strip()
    return False, None


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
    if pid is None or not _is_our_inhibitor(pid):
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
        # Durable: idle_state.json holds the user's original settings and must
        # survive the abrupt reboot a reboot test can issue moments later.
        try:
            from harness.artifacts.manifest import durable_write_text
            durable_write_text(IDLE_STATE_PATH, json.dumps(state, indent=2))
        except Exception:
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
            bus_failures = 0
            for schema, key, _ in GNOME_KEYS:
                if not _gsettings_key_exists(schema, key):
                    continue
                bus_ok, value = _gsettings_get2(schema, key)
                if bus_ok and value is not None:
                    state["gsettings"][f"{schema}|{key}"] = value
                else:
                    bus_failures += 1
            if bus_failures:
                _log(
                    f"WARNING: could not read {bus_failures} GNOME key(s) — session bus "
                    "likely unreachable; their originals will NOT be restored"
                )

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


# Read-back subset asserted after every GNOME apply and by the guard test in
# tests/idle_guard.py.  These are the keys that actually decide whether the
# screen blanks/locks, so confirming just these is enough to prove the
# protection took effect; the full GNOME_KEYS list is still applied best-effort.
GNOME_READBACK: list[tuple[str, str, str]] = [
    ("org.gnome.desktop.session", "idle-delay", "uint32 0"),
    ("org.gnome.desktop.screensaver", "lock-enabled", "false"),
]


def disable_idle() -> dict:
    """Disable idle blanking, screen locking and idle suspend.

    Returns a structured report::

        {"backend": "gnome" | "cosmic" | None,
         "applied": ["schema|key", ...] | ["cosmic/file", ...],
         "values": {"schema|key": "read-back value"},   # gnome only
         "readback_ok": bool | None,
         "errors": ["human readable failure", ...]}

    A key whose read FAILED (session bus unreachable — the classic failure
    when pytest runs under sudo or from the systemd resume unit) is reported
    as an error instead of being skipped as "not defined"; ``gsettings
    list-keys`` is what distinguishes the two. Applied GNOME keys are read
    back and logged, so a ``grep`` for ``[idle]`` in a resume log shows the
    actual values rather than just a count.
    """
    report: dict = {"backend": None, "applied": [], "values": {}, "readback_ok": None, "errors": []}

    desktop = _desktop_kind()
    report["backend"] = desktop
    if desktop is None:
        _log("unknown desktop; nothing to disable")
        report["errors"].append("desktop undetected (set XDG_CURRENT_DESKTOP or fix session detection)")
        return report

    if desktop == "gnome":
        if not _gsettings_available():
            _log("gsettings not found; cannot disable GNOME idle settings")
            report["errors"].append("gsettings not installed")
            return report
        for schema, key, value in GNOME_KEYS:
            if not _gsettings_key_exists(schema, key):
                # Only silence genuinely-undefined keys (older/newer schemas,
                # Ubuntu-only keys); a failed list-keys probe is an error.
                if _gsettings_list_keys(schema) is None:
                    report["errors"].append(f"{schema}: gsettings cannot reach the session bus")
                continue
            bus_ok, _current = _gsettings_get2(schema, key)
            if not bus_ok:
                report["errors"].append(f"{schema} {key}: read failed (session bus?)")
                continue
            if not _gsettings_set(schema, key, value):
                report["errors"].append(f"{schema} {key}: set failed")
                continue
            ok, actual = _gsettings_get2(schema, key)
            if not ok:
                report["errors"].append(f"{schema} {key}: read-back failed")
                continue
            report["applied"].append(f"{schema}|{key}")
            report["values"][f"{schema}|{key}"] = actual
            _log(f"gnome {schema} {key} = {actual}")
        # Verify the critical subset actually reads as disabled.  A critical
        # key we could not probe or set must make readback_ok False — "nothing
        # was verified" is not "verified fine".
        rb_missing = False
        for schema, key, want in GNOME_READBACK:
            if not _gsettings_key_exists(schema, key):
                rb_missing = True
                report["errors"].append(
                    f"critical key {schema} {key} unverifiable "
                    "(undefined or session bus unreachable)"
                )
                continue
            got = report["values"].get(f"{schema}|{key}")
            if got is None:
                got = _gsettings_get(schema, key)
            if got != want:
                rb_missing = True
                report["errors"].append(f"read-back {schema} {key}={got!r}, wanted {want!r}")
        report["readback_ok"] = not rb_missing
        _log(
            f"applied {len(report['applied'])} GNOME idle setting(s)"
            + ("" if report["readback_ok"] else " — READ-BACK INCOMPLETE")
        )
        # Reuse an inhibitor from an earlier attempt in this run, if alive.
        pid = (_load_state() or {}).get("inhibitor_pid")
        if not _is_our_inhibitor(pid):
            pid = _start_gnome_inhibitor()
        if pid:
            _update_state(inhibitor_pid=pid)
        return report

    if desktop == "cosmic":
        directory = _cosmic_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            _log(f"could not create {directory}: {exc}")
            report["errors"].append(f"could not create {directory}: {exc}")
            return report
        for key in COSMIC_IDLE_KEYS:
            path = directory / key
            try:
                path.write_text("None", encoding="utf-8")
            except Exception as exc:
                _log(f"could not write {key}: {exc}")
                report["errors"].append(f"could not write {path}: {exc}")
                continue
            try:
                if path.read_text(encoding="utf-8") != "None":
                    report["errors"].append(f"read-back mismatch for {path}")
                    continue
            except Exception as exc:
                report["errors"].append(f"read-back failed for {path}: {exc}")
                continue
            report["applied"].append(f"cosmic/{key}")
        report["readback_ok"] = len(report["applied"]) == len(COSMIC_IDLE_KEYS)
        _log(f"applied {len(report['applied'])} COSMIC idle setting(s)")
        return report

    return report


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
