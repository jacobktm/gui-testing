"""Reboot-aware helpers shared by every test suite.

Public entry points::

    from harness.reboot import prepare_reboot, finish_reboot

    setup = prepare_reboot(run_dir, pytest_args=["tests/..."])
    ...
    finish_reboot(username=setup.username)

``prepare_reboot`` detects the desktop (GNOME/gdm, COSMIC/greetd), enables
autologin for the *graphical* user, and installs a systemd user unit that
re-runs pytest after the reboot.  ``finish_reboot`` undoes both.

The individual pieces are exposed for tests and for manual recovery::

    python -m harness.reboot status
    python -m harness.reboot restore
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import pwd
import sys

from .autostart import ResumePlan, install_resume_unit, remove_resume_unit
from .resume import (
    ResumeState,
    bump_attempts,
    load_completed,
    record_completed,
    resume_dir,
)
from .session import (
    AutologinManager,
    AutologinResult,
    DesktopSession,
    detect_desktop,
    detect_display_manager,
    detect_gui_user,
    detect_session,
    render_cosmic_autologin,
    render_gdm_autologin,
    render_lightdm_autologin,
    render_sddm_autologin,
    force_restore_autologin,
    restore_autologin,
)

__all__ = [
    "AutologinManager",
    "AutologinResult",
    "DesktopSession",
    "RebootSetup",
    "ResumePlan",
    "ResumeState",
    "bump_attempts",
    "detect_desktop",
    "detect_display_manager",
    "detect_gui_user",
    "detect_session",
    "finish_reboot",
    "force_restore_autologin",
    "install_resume_unit",
    "load_completed",
    "prepare_reboot",
    "record_completed",
    "remove_resume_unit",
    "render_cosmic_autologin",
    "render_gdm_autologin",
    "render_lightdm_autologin",
    "render_sddm_autologin",
    "restore_autologin",
    "resume_dir",
]


@dataclass(frozen=True)
class RebootSetup:
    """Result of preparing a session for reboot/resume testing."""

    session: DesktopSession
    autologin: AutologinResult
    resume: ResumePlan

    @property
    def username(self) -> str:
        return self.session.username

    @property
    def prepared(self) -> bool:
        return self.autologin.enabled and self.resume.installed

    def describe(self) -> str:
        parts = [
            f"desktop={self.session.desktop}",
            f"display_manager={self.session.display_manager}",
            f"user={self.session.username}",
            f"autologin={'ok' if self.autologin.enabled else 'off'}",
            f"resume_unit={'ok' if self.resume.installed else 'off'}",
        ]
        if not self.autologin.enabled and self.autologin.reason:
            parts.append(f"autologin_reason={self.autologin.reason}")
        if not self.resume.installed and self.resume.reason:
            parts.append(f"resume_reason={self.resume.reason}")
        return " ".join(parts)


def prepare_reboot(
    run_dir: Path | str,
    *,
    username: str | None = None,
    pytest_args: list[str] | None = None,
    workdir: Path | str | None = None,
    python: str | None = None,
) -> RebootSetup:
    """Enable autologin and install the pytest resume unit for ``run_dir``."""
    session = detect_session(username)
    autologin = AutologinManager(session).enable()
    resume = install_resume_unit(
        run_dir,
        username=session.username,
        pytest_args=pytest_args,
        workdir=workdir,
        python=python,
    )
    return RebootSetup(session=session, autologin=autologin, resume=resume)


def finish_reboot(*, username: str | None = None) -> bool:
    """Remove the resume unit and restore the original autologin config.

    Tries multiple users and locations to ensure cleanup happens even if
    the detected user is wrong (common on Pop!_OS GNOME/COSMIC).
    """
    print("[finish_reboot] START", file=sys.stderr, flush=True)
    target = username or detect_gui_user()
    print(f"[finish_reboot] target user: {target}", file=sys.stderr, flush=True)
    # Try the detected user and the current user.
    users_to_try = [target]
    try:
        current = pwd.getpwuid(os.getuid()).pw_name
        if current not in users_to_try:
            users_to_try.append(current)
    except KeyError:
        pass

    unit_removed = False
    for u in users_to_try:
        if remove_resume_unit(username=u):
            unit_removed = True

    # Also try to find unit files in all home directories.
    for home in Path("/home").iterdir():
        if not home.is_dir():
            continue
        unit_file = home / ".config" / "systemd" / "user" / "gui-testing-resume.service"
        if unit_file.exists():
            try:
                unit_file.unlink()
                unit_removed = True
            except OSError:
                try:
                    subprocess.run(
                        ["sudo", "-n", "rm", "-f", str(unit_file)],
                        capture_output=True, text=True, timeout=10,
                    )
                    unit_removed = True
                except Exception:
                    pass

    # For COSMIC, try force_restore first (doesn't depend on state file).
    restored = False
    # Try via sudo (sudoers may still be in place).
    try:
        import subprocess
        r = subprocess.run(
            ["sudo", "-n", "python3", "-m", "harness.reboot", "force-restore"],
            capture_output=True, text=True, timeout=10,
        )
        print(f"[finish_reboot] sudo force-restore: rc={r.returncode} stdout={r.stdout.strip()} stderr={r.stderr.strip()}", file=sys.stderr, flush=True)
        if r.returncode == 0:
            restored = True
    except Exception as e:
        print(f"[finish_reboot] sudo force-restore exception: {e}", file=sys.stderr, flush=True)
    # Fallback: try in-process (works if running as root).
    if not restored:
        try:
            from .session import force_restore_autologin
            restored = force_restore_autologin()
            print(f"[finish_reboot] in-process force_restore: {restored}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[finish_reboot] in-process force_restore exception: {e}", file=sys.stderr, flush=True)
    if not restored:
        restored = restore_autologin()
        print(f"[finish_reboot] restore_autologin: {restored}", file=sys.stderr, flush=True)
    # Clean up persistent reboot marker.
    if username:
        try:
            from handlers.system76_power import System76Power
        except Exception:
            pass
    try:
        # Find and remove persistent markers in all run dirs.
        artifacts_root = Path(os.environ.get("GUI_TESTING_ARTIFACTS", "artifacts"))
        if not artifacts_root.is_absolute():
            artifacts_root = Path.cwd() / artifacts_root
        for marker in artifacts_root.glob("*/reboot-marker"):
            try:
                marker.unlink()
            except OSError:
                pass
    except Exception:
        pass
    # Also try removing from the run dir if available.
    try:
        run_dir = getattr(getattr(finish_reboot, "_last_run_dir", None), None, None)
    except Exception:
        pass

    # Also try to clean up sudoers (best-effort).
    try:
        subprocess.run(
            ["sudo", "-n", "rm", "-f", "/etc/sudoers.d/gui-testing"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass
    return bool(unit_removed or restored)
