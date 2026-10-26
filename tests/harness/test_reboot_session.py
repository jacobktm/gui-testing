"""Unit tests for the general reboot/session helpers (no system changes)."""

from __future__ import annotations

from pathlib import Path

from harness.reboot import (
    autostart,
    render_cosmic_autologin,
    render_gdm_autologin,
    resume,
    session,
)


def test_cosmic_autologin_replaces_initial_session():
    existing = (
        "[terminal]\nvt = \"1\"\n\n"
        "[general]\nservice = \"cosmic-greeter\"\n\n"
        "[default_session]\ncommand = \"cosmic-greeter-start\"\nuser = \"cosmic-greeter\"\n\n"
        "[initial_session]\ncommand = \"cosmic-session\"\nuser = \"old\"\n"
    )
    rendered = render_cosmic_autologin(existing, "alice", "start-cosmic")

    assert rendered.count("[initial_session]") == 1
    assert 'command = "start-cosmic"' in rendered
    assert 'user = "alice"' in rendered
    assert 'user = "old"' not in rendered
    assert "[default_session]" in rendered
    assert 'command = "cosmic-greeter-start"' in rendered


def test_cosmic_autologin_idempotent():
    once = render_cosmic_autologin("", "alice", "start-cosmic")
    twice = render_cosmic_autologin(once, "alice", "start-cosmic")
    assert once == twice


def test_gdm_autologin_preserves_unrelated_sections():
    existing = "[daemon]\n# comment\n\n[security]\nAllowRoot=false\n"
    rendered = render_gdm_autologin(existing, "alice")

    assert "AutomaticLoginEnable=true" in rendered
    assert "AutomaticLogin=alice" in rendered
    assert "[security]" in rendered
    assert "AllowRoot=false" in rendered
    assert rendered.count("[daemon]") == 1


def test_gdm_autologin_replace_existing_keys():
    existing = "[daemon]\nAutomaticLoginEnable=false\nAutomaticLogin=bob\n"
    rendered = render_gdm_autologin(existing, "alice")

    assert rendered.count("AutomaticLogin=") == 1
    assert "AutomaticLogin=alice" in rendered
    assert "AutomaticLogin=bob" not in rendered


def test_gui_user_prefers_graphical_session(monkeypatch):
    monkeypatch.setattr(
        session,
        "_logind_sessions",
        lambda: [
            {
                "Id": "3",
                "Name": "alice",
                "Type": "wayland",
                "Class": "user",
                "State": "active",
                "Remote": "no",
            }
        ],
    )
    monkeypatch.setattr(session, "_runtime_socket_owner", lambda: "carol")

    detected = session.detect_gui_user(environ={"SUDO_USER": "root", "USER": "root"})
    assert detected == "alice"


def test_gui_user_falls_back_to_socket_owner(monkeypatch):
    monkeypatch.setattr(session, "_logind_sessions", lambda: [])
    monkeypatch.setattr(session, "_runtime_socket_owner", lambda: "carol")

    assert session.detect_gui_user(environ={"USER": "root"}) == "carol"


def test_gui_user_falls_back_to_sudo_user(monkeypatch):
    monkeypatch.setattr(session, "_logind_sessions", lambda: [])
    monkeypatch.setattr(session, "_runtime_socket_owner", lambda: None)

    assert session.detect_gui_user(environ={"SUDO_USER": "alice", "USER": "root"}) == "alice"


def test_build_pytest_args_strips_resume_option():
    args = ["tests/", "-q", "--resume-run", "/tmp/run", "--resume-run=/tmp/other"]
    assert autostart.build_pytest_args(args) == ["tests/", "-q"]


def test_resume_script_targets_run_dir_and_cosmic():
    script = autostart.build_resume_script(
        "/tmp/run-123",
        pytest_args=["tests/"],
        workdir="/home/alice/testing",
        python="/usr/bin/python3",
        username="alice",
        max_attempts=4,
    )

    assert "GUI_TESTING_RESUME_RUN=/tmp/run-123" in script
    assert "cd /home/alice/testing" in script
    assert "XDG_CURRENT_DESKTOP" in script
    assert "WAYLAND_DISPLAY" in script
    assert "/tmp/run-123/resume/attempts" in script
    assert "-gt 4" in script
    assert "--resume-run /tmp/run-123" in script


def test_resume_state_roundtrip(tmp_path: Path):
    state = resume.ResumeState(tmp_path)
    state.mark("tests/a.py::test_one")
    state.mark("tests/a.py::test_two")
    state.mark("tests/a.py::test_one")

    assert state.completed() == {"tests/a.py::test_one", "tests/a.py::test_two"}
    assert state.next_attempt(limit=2) is True
    assert state.next_attempt(limit=2) is True
    assert state.next_attempt(limit=2) is False


def test_handover_is_noop_for_non_root(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(session.os, "geteuid", lambda: 1000)
    assert session.handover_run_dir(tmp_path) is False


def test_enable_refuses_unreadable_config(tmp_path: Path, monkeypatch):
    config = tmp_path / "cosmic-greeter.toml"
    config.write_text("[general]\nservice = \"cosmic-greeter\"\n")
    manager = session.AutologinManager(
        session.DesktopSession("cosmic", "cosmic-greeter", "alice", "start-cosmic")
    )
    monkeypatch.setattr(session, "_read_privileged", lambda path: None)
    monkeypatch.setattr(manager, "_target", lambda user: (config, "replacement"))

    result = manager.enable()

    assert result.enabled is False
    assert "refusing to modify" in result.reason
    assert config.read_text() == "[general]\nservice = \"cosmic-greeter\"\n"

