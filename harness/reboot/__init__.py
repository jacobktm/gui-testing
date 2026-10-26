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
    """Remove the resume unit and restore the original autologin config."""
    target = username or detect_gui_user()
    unit_removed = remove_resume_unit(username=target)
    restored = restore_autologin()
    return bool(unit_removed and restored)
