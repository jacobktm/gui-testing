"""Command line helper for reboot-aware test setup.

Usage::

    python -m harness.reboot status     # show detected desktop/user/state
    python -m harness.reboot enable     # enable autologin + resume unit
    python -m harness.reboot restore    # restore autologin + remove unit

Useful when a run was interrupted after it enabled autologin.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .autostart import install_resume_unit, remove_resume_unit, unit_path_for
from .session import AUTOLOGIN_STATE, AutologinManager, detect_gui_user, detect_session


def _status(username: str | None) -> dict[str, object]:
    session = detect_session(username)
    state_exists = AUTOLOGIN_STATE.exists()
    unit = unit_path_for(session.username)
    return {
        "desktop": session.desktop,
        "display_manager": session.display_manager,
        "username": session.username,
        "session_command": session.session_command,
        "autologin_backup": str(AUTOLOGIN_STATE) if state_exists else None,
        "resume_unit": str(unit) if unit.exists() else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m harness.reboot")
    parser.add_argument("action", choices=("status", "enable", "restore"))
    parser.add_argument("--user", help="GUI user (defaults to the detected session user)")
    parser.add_argument("--run-dir", help="artifact run directory for the resume unit")
    parser.add_argument("--workdir", help="working directory for the resumed pytest run")
    args = parser.parse_args(argv)

    session = detect_session(args.user)
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
                pytest_args=[],
                workdir=args.workdir,
            )
            print(f"resume unit: {'installed' if plan.installed else 'failed'} ({plan.unit_path or plan.reason})")
        return 0 if result.enabled else 1

    restored = AutologinManager(session).restore()
    removed = remove_resume_unit(username=session.username)
    print(f"autologin restored: {restored}; resume unit removed: {removed}")
    return 0 if restored and removed else 1


if __name__ == "__main__":
    sys.exit(main())
