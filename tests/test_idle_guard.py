"""Fail fast if idle/lock protection is not actually active.

conftest's collection sort runs this before every other test (same mechanism
that pins the screenshot-permission smoke test). A silently-ineffective idle
disable — session bus unreachable under sudo or in the systemd resume unit,
undetected desktop, missing backend — otherwise only shows up ~20 minutes
later, as every GUI capture seeing a bare or locked desktop. Failing here
stops the run before any reboot test can strand the machine in a locked
session mid-multi-boot-run.
"""
from __future__ import annotations

import pytest


class TestIdleGuard:
    def test_idle_protection_active(self, pytestconfig):
        from harness.reboot.idle import (
            COSMIC_IDLE_KEYS,
            GNOME_READBACK,
            _cosmic_dir,
            _desktop_kind,
            _gsettings_get2,
            _gsettings_key_exists,
        )

        desktop = _desktop_kind()
        if desktop is None:
            pytest.skip(
                "desktop undetected (XDG_CURRENT_DESKTOP/XDG_SESSION_DESKTOP/"
                "DESKTOP_SESSION unset and session detection failed) — idle "
                "protection cannot be verified"
            )

        problems: list[str] = []
        if desktop == "gnome":
            for schema, key, want in GNOME_READBACK:
                if not _gsettings_key_exists(schema, key):
                    problems.append(f"{schema} {key}: undefined or session bus unreachable")
                    continue
                bus_ok, got = _gsettings_get2(schema, key)
                if not bus_ok:
                    problems.append(f"{schema} {key}: read failed")
                elif got != want:
                    problems.append(f"{schema} {key}={got!r}, expected {want!r}")
        elif desktop == "cosmic":
            directory = _cosmic_dir()
            for key in COSMIC_IDLE_KEYS:
                path = directory / key
                if not path.exists():
                    problems.append(f"{path} missing (idle timers not disabled)")
                    continue
                try:
                    content = path.read_text(encoding="utf-8").strip()
                except OSError as exc:
                    problems.append(f"{path}: unreadable ({exc})")
                    continue
                if content != "None":
                    problems.append(f"{path}={content!r}, expected 'None'")

        report = getattr(pytestconfig, "_gui_idle_report", None)

        if problems:
            detail = "\n".join(f"  - {p}" for p in problems)
            if report is not None:
                detail += f"\n  configure-time report: {report}"
            pytest.fail(
                "idle/lock protection is NOT active; GUI tests would run under "
                f"the real policy and screenshots may hit a locked screen:\n{detail}"
            )
