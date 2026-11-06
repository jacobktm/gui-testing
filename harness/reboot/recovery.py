"""Run marker and boot-time recovery for reboot-aware runs.

A reboot kills pytest, so the harness must leave the machine in a state that can
be undone *later* — autologin on, a passwordless sudo rule, a resume unit.  Trust
ing the pytest process to undo it is not enough: that process is the thing the
reboot kills, and it can also die to Ctrl-C or a crash.  A leaked autologin
plus resume unit is exactly the state that makes a throwaway test install stop
being a usable test install.

Two pieces make the machine converge back on its own:

1. A per-user **run marker** (this module) written next to the other per-user
   harness state.  It is refreshed on every boot of a multi-boot run, so a live
   run is always recognisable — and writing it needs no privilege at all.
2. A root-owned **recovery unit** installed by ``pytest.sh`` that runs at every
   boot: if no marker is fresh, it revokes the sudoers rule, restores the
   display-manager configuration, deletes resume units, and disables itself.

The unit stays enabled after a clean run precisely so that the next boot
verifies the machine is clean; ``pytest.sh`` re-enables it for each new run.
:func:`build_recover_script` and :func:`build_recover_unit` are the single
source of truth for what gets installed, and they are pure text so they can be
generated and syntax-checked without root.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

__all__ = [
    "DEFAULT_MAX_RUN_AGE_MIN",
    "KEEP_SETUP_FLAG",
    "RECOVER_SCRIPT_PATH",
    "RECOVER_UNIT_NAME",
    "RECOVER_UNIT_PATH",
    "RESUME_GAVE_UP_NAME",
    "RUN_ACTIVE_NAME",
    "build_recover_script",
    "build_recover_unit",
    "clear_run_active",
    "mark_run_active",
    "run_active_age_seconds",
    "state_dir",
]

#: How long a run marker stays believable.  A multi-boot run refreshes it on
#: every boot, so this only needs to outlast one deliberate pause.
DEFAULT_MAX_RUN_AGE_MIN = 720  # 12 hours

RUN_ACTIVE_NAME = "run-active"
RESUME_GAVE_UP_NAME = "GAVE_UP"

#: Touch this to tell the boot-time recovery to leave everything alone (useful
#: while hand-debugging a run that is waiting to be resumed).
KEEP_SETUP_FLAG = Path("/var/lib/gui-testing/keep-setup")

RECOVER_UNIT_NAME = "gui-testing-recover.service"
RECOVER_UNIT_PATH = Path("/etc/systemd/system") / RECOVER_UNIT_NAME
RECOVER_SCRIPT_PATH = Path("/usr/local/libexec") / "gui-testing-recover"


def state_dir() -> Path:
    """Per-user harness state (same directory the idle/graphics state uses)."""
    return Path.home() / ".local" / "share" / "gui-testing"


def run_active_path() -> Path:
    return state_dir() / RUN_ACTIVE_NAME


def _durable_write(path: Path, text: str) -> None:
    """Atomically write *text* with fsyncs (stdlib-only local copy).

    The run marker is the only thing standing between a mid-run reboot and
    the recovery unit tearing down a live run's setup; losing it to a crash
    or power cut would abort the run.  Kept local so this module stays
    importable without the artifacts package (the recovery path must work
    in minimal environments).
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def mark_run_active(run_dir: Path | str, *, note: str | None = None) -> bool:
    """Write/refresh the marker that tells recovery a run is in progress."""
    payload = {
        "run_dir": str(run_dir),
        "updated_epoch": int(time.time()),
        "pid": os.getpid(),
    }
    if note:
        payload["note"] = note
    try:
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _durable_write(run_active_path(), json.dumps(payload, indent=2) + "\n")
        return True
    except OSError:
        return False


def clear_run_active() -> bool:
    try:
        run_active_path().unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def run_active_age_seconds() -> float | None:
    """Seconds since the marker was refreshed, or ``None`` if there is none."""
    try:
        return max(0.0, time.time() - run_active_path().stat().st_mtime)
    except OSError:
        return None


def build_recover_script(*, max_age_min: int = DEFAULT_MAX_RUN_AGE_MIN) -> str:
    """POSIX shell body for the boot-time recovery unit."""
    return f"""#!/bin/sh
# Installed by pytest.sh - do not edit, regenerated on every run.
# Brings the machine back to a clean, testable state when no test run is in
# progress: revokes the passwordless sudo rule, restores the display-manager
# configuration, and deletes resume units.  Runs at every boot, then disables
# itself; pytest.sh re-enables it whenever a run starts.
set -u

MAX_AGE_MIN="${{GUI_TESTING_RECOVER_MAX_AGE_MIN:-{max_age_min}}}"
SUDOERS=/etc/sudoers.d/gui-testing
HELPER=/usr/local/libexec/gui-testing-privileged
KEEP_SETUP={KEEP_SETUP_FLAG}

if [ -e "$KEEP_SETUP" ]; then
    echo "gui-testing-recover: $KEEP_SETUP present; leaving setup in place"
    exit 0
fi

# A fresh marker means a run is mid-flight (it was just rebooted and is about to
# resume).  Untangle nothing until it goes stale.
for marker in /home/*/.local/share/gui-testing/{RUN_ACTIVE_NAME} /root/.local/share/gui-testing/{RUN_ACTIVE_NAME}; do
    [ -f "$marker" ] || continue
    if [ -n "$(find "$marker" -mmin "-$MAX_AGE_MIN" 2>/dev/null)" ]; then
        echo "gui-testing-recover: run marker is fresh ($marker); leaving setup in place"
        exit 0
    fi
done

echo "gui-testing-recover: no active run marker; restoring machine state"

# Revoke passwordless root first, so nothing can use a stale grant.
if [ -e "$SUDOERS" ]; then
    rm -f "$SUDOERS"
    echo "gui-testing-recover: removed $SUDOERS"
fi

# Preferred path: the root-owned helper knows how to restore each desktop's
# autologin configuration and clear its own state.
if [ -x "$HELPER" ]; then
    "$HELPER" recover || echo "gui-testing-recover: helper recover reported a problem" >&2
fi

# Fallback for when the helper (or its snapshot) is gone: delete what the
# harness created, including the systemd unit and its enable symlink (the
# symlink is checked separately because it can dangle after the unit file is
# already gone).
for unit in /home/*/.config/systemd/user/gui-testing-resume.service /root/.config/systemd/user/gui-testing-resume.service; do
    [ -e "$unit" ] || continue
    rm -f "$unit"
    rm -f "$(dirname "$unit")/graphical-session.target.wants/gui-testing-resume.service"
    echo "gui-testing-recover: removed $unit"
done
for link in /home/*/.config/systemd/user/graphical-session.target.wants/gui-testing-resume.service /root/.config/systemd/user/graphical-session.target.wants/gui-testing-resume.service; do
    [ -L "$link" ] || continue
    rm -f "$link"
    echo "gui-testing-recover: removed dangling $link"
done
for marker in /home/*/.local/share/gui-testing/{RUN_ACTIVE_NAME} /root/.local/share/gui-testing/{RUN_ACTIVE_NAME}; do
    [ -f "$marker" ] && rm -f "$marker"
done

# Clean for this boot; the next ./pytest.sh re-arms us.
systemctl disable {RECOVER_UNIT_NAME} >/dev/null 2>&1 || true
echo "gui-testing-recover: done"
exit 0
"""


def build_recover_unit(*, max_age_min: int = DEFAULT_MAX_RUN_AGE_MIN) -> str:
    """systemd unit that runs :func:`build_recover_script` at every boot."""
    return f"""[Unit]
Description=Undo GUI test harness leftovers when no run is active
After=multi-user.target

[Service]
Type=oneshot
Environment="GUI_TESTING_RECOVER_MAX_AGE_MIN={max_age_min}"
ExecStart={RECOVER_SCRIPT_PATH}

[Install]
WantedBy=multi-user.target
"""
