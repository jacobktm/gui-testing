"""Command line entry point for reboot-aware test setup.

In production the only way this runs as root is through the root-owned wrapper
that ``pytest.sh`` installs at ``/usr/local/libexec/gui-testing-privileged``
(see :mod:`harness.reboot.helper`).  Invoke that wrapper, not this module, for
anything privileged::

    sudo -n /usr/local/libexec/gui-testing-privileged status
    sudo -n /usr/local/libexec/gui-testing-privileged enable
    sudo -n /usr/local/libexec/gui-testing-privileged restore
    sudo -n /usr/local/libexec/gui-testing-privileged cleanup

``python -m harness.reboot`` remains handy unprivileged (``status``) and when
already running as root, e.g. for manual recovery of an interrupted run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import finish_reboot, helper
from .autostart import install_resume_unit, remove_resume_unit, unit_path_for
from .session import AUTOLOGIN_STATE, AutologinManager, detect_gui_user, detect_session

SUDOERS_FILE = helper.SUDOERS_FILE

# Privileged primitives implemented in :mod:`harness.reboot.helper`.
SERVER_ACTIONS = helper.SERVER_ACTIONS
ALL_ACTIONS = (
    "status",
    "enable",
    "restore",
    "cleanup",
    "cleanup-all",
    "force-restore",
    "recover",
    *SERVER_ACTIONS,
)


def _status(username: str | None) -> dict[str, object]:
    session = detect_session(username)
    state_exists = AUTOLOGIN_STATE.exists()
    unit = unit_path_for(session.username)
    sudoers_exists = SUDOERS_FILE.exists()
    return {
        "desktop": session.desktop,
        "display_manager": session.display_manager,
        "username": session.username,
        "session_command": session.session_command,
        "autologin_backup": str(AUTOLOGIN_STATE) if state_exists else None,
        "resume_unit": str(unit) if unit.exists() else None,
        "passwordless_sudo": sudoers_exists,
    }


def _cmd_cleanup(username: str | None) -> int:
    """Remove the passwordless sudoers rule.

    The helper runs as root, so it can unlink the file itself.  The rule is only
    ever *removed* — never written — so a run can never widen its own grant.
    """
    if not SUDOERS_FILE.exists():
        return 0
    if os.geteuid() == 0:
        try:
            SUDOERS_FILE.unlink()
            print(f"Removed {SUDOERS_FILE}")
            return 0
        except OSError as exc:
            print(f"Failed to remove {SUDOERS_FILE}: {exc}", file=sys.stderr)
            return 1
    if helper.priv_cleanup_sudoers():
        print(f"Removed {SUDOERS_FILE}")
        return 0
    # No passwordless grant left (that is the normal state once cleanup has
    # run): fall back to the operator, who can authorize interactively.
    try:
        result = subprocess.run(
            ["sudo", "rm", "-f", str(SUDOERS_FILE)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"Removed {SUDOERS_FILE}")
            return 0
        print(f"Failed to remove {SUDOERS_FILE}: {result.stderr.strip()}")
        return 1
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Error: {e}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gui-testing-privileged")
    parser.add_argument("action", choices=ALL_ACTIONS)
    parser.add_argument(
        "args",
        nargs="*",
        metavar="ARG",
        help="argument for read/write/remove/sysrq (payload for write goes on stdin)",
    )
    parser.add_argument("--user", help="GUI user (defaults to the detected session user)")
    parser.add_argument("--run-dir", help="artifact run directory for the resume unit")
    parser.add_argument("--workdir", help="working directory for the resumed pytest run")
    parsed = parser.parse_args(argv)
    action, extra = parsed.action, parsed.args

    if action in SERVER_ACTIONS:
        if action not in ("reboot", "reboot-graceful") and not extra:
            print(f"{action} requires an argument", file=sys.stderr, flush=True)
            return 2
        rc, output = helper.dispatch(action, extra)
        if output:
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
        return rc

    if action == "recover":
        # Boot-time repair path (recovery unit calls ``$HELPER recover``).
        # Detects the user itself; must not need a GUI session to exist.
        ok = finish_reboot(username=parsed.user)
        print(f"recover: {'done' if ok else 'incomplete (machine may need attention)'}", flush=True)
        return 0 if ok else 1

    session = detect_session(parsed.user)

    if action == "status":
        print(json.dumps(_status(session.username), indent=2))
        return 0

    if action == "enable":
        result = AutologinManager(session).enable()
        print(f"autologin: {'enabled' if result.enabled else 'failed'} ({result.path or result.reason})")
        if parsed.run_dir:
            plan = install_resume_unit(
                Path(parsed.run_dir),
                username=session.username,
                workdir=parsed.workdir,
            )
            print(f"resume unit: {'installed' if plan.installed else 'failed'} ({plan.unit_path or plan.reason})")
        return 0 if result.enabled else 1

    if action == "force-restore":
        from .session import force_restore_autologin
        restored = force_restore_autologin()
        print(f"force restore: {restored}")
        return 0 if restored else 1

    if action == "cleanup":
        return _cmd_cleanup(session.username)

    if action == "cleanup-all":
        # Remove sudoers, resume unit, and restore autologin.
        _cmd_cleanup(session.username)
        remove_resume_unit(username=session.username)
        restored = AutologinManager(session).restore()
        if not restored:
            from .session import force_restore_autologin
            restored = force_restore_autologin()
            print(f"force restore: {restored}")
        print(f"autologin restored: {restored}")
        # Clean up persistent reboot markers.
        import glob
        for marker in glob.glob(str(Path.home() / ".local" / "share" / "gui-testing" / ".." / ".." / ".." / ".." / "artifacts" / "*" / "reboot-marker")):
            try:
                Path(marker).unlink()
            except Exception:
                pass
        # Also check common locations.
        for root in (Path("/home") / os.environ.get("USER", "system76"), Path.cwd()):
            for marker in root.rglob("reboot-marker"):
                try:
                    marker.unlink()
                except Exception:
                    pass
        return 0 if restored else 1

    restored = AutologinManager(session).restore()
    removed = remove_resume_unit(username=session.username)
    print(f"autologin restored: {restored}; resume unit removed: {removed}")
    return 0 if restored and removed else 1


if __name__ == "__main__":
    sys.exit(main())
