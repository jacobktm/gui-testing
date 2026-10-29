"""Command line helper for reboot-aware test setup.

Usage::

    python -m harness.reboot status     # show detected desktop/user/state
    python -m harness.reboot enable     # enable autologin + resume unit
    python -m harness.reboot restore    # restore autologin + remove unit
    python -m harness.reboot cleanup    # remove passwordless sudoers rule

Useful when a run was interrupted after it enabled autologin.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

from .autostart import install_resume_unit, remove_resume_unit, unit_path_for
from .session import AUTOLOGIN_STATE, AutologinManager, detect_gui_user, detect_session

SUDOERS_FILE = Path("/etc/sudoers.d/gui-testing")


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
    """Remove the passwordless sudoers rule."""
    if SUDOERS_FILE.exists():
        try:
            subprocess.run(
                ["sudo", "-n", "rm", "-f", str(SUDOERS_FILE)],
                capture_output=True, text=True, timeout=10,
            )
            if not SUDOERS_FILE.exists():
                print(f"Removed {SUDOERS_FILE}")
                return 0
        except (OSError, subprocess.SubprocessError):
            pass
    # Fallback: try without -n (interactive)
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
    parser = argparse.ArgumentParser(prog="python -m harness.reboot")
    parser.add_argument("action", choices=("status", "enable", "restore", "cleanup", "cleanup-all", "force-restore", "reboot"))
    parser.add_argument("--user", help="GUI user (defaults to the detected session user)")
    parser.add_argument("--run-dir", help="artifact run directory for the resume unit")
    parser.add_argument("--workdir", help="working directory for the resumed pytest run")
    args = parser.parse_args(argv)

    session = detect_session(args.user)
    if args.action == "reboot":
        # Direct kernel reboot(2) syscall via ctypes.  Runs as root under
        # sudo (the sudoers rule whitelists this module); the syscall either
        # reboots the machine immediately or fails loudly.
        os.sync()
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        rc = libc.reboot(ctypes.c_uint(0x01234567))  # RB_AUTOBOOT
        if rc != 0:
            errno = ctypes.get_errno()
            print(f"reboot syscall failed: errno={errno} ({os.strerror(errno)})",
                  file=sys.stderr, flush=True)
            sys.stdout.flush()
            return 1
        # If the syscall succeeded, the kernel is already rebooting and this
        # process dies before reaching this point.
        return 0

    if args.action == "status":
        print(json.dumps(_status(session.username), indent=2))
        return 0

    if args.action == "enable":
        result = AutologinManager(session).enable()
        print(f"autologin: {'enabled' if result.enabled else 'failed'} ({result.path or result.reason})")
        if args.run_dir:
            plan = install_resume_unit(
                Path(args.run_dir),
                username=session.username,
                workdir=args.workdir,
            )
            print(f"resume unit: {'installed' if plan.installed else 'failed'} ({plan.unit_path or plan.reason})")
        return 0 if result.enabled else 1

    if args.action == "force-restore":
        from .session import force_restore_autologin
        restored = force_restore_autologin()
        print(f"force restore: {restored}")
        return 0 if restored else 1

    if args.action == "cleanup":
        return _cmd_cleanup(session.username)

    if args.action == "cleanup-all":
        # Remove sudoers, resume unit, and restore autologin.
        _cmd_cleanup(session.username)
        from .autostart import remove_resume_unit
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
