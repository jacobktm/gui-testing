import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.artifacts import KeepFailures, KeepLast, RetentionPlan, RunArtifacts
from harness.reboot import (
    finish_reboot,
    load_completed,
    prepare_reboot,
    record_completed,
)

PROGRAMS = ["system76-power"]

__all__ = [
    "PROGRAMS",
    "pytest_addoption",
    "pytest_collection_modifyitems",
    "pytest_collection_finish",
    "pytest_configure",
    "pytest_runtest_makereport",
    "pytest_sessionfinish",
    "pytest_terminal_summary",
    "artifacts",
    "artifacts_root",
]

RESUME_ENV = "GUI_TESTING_RESUME_RUN"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _artifacts_root(config) -> Path:
    root = os.environ.get("GUI_TESTING_ARTIFACTS")
    if root:
        return Path(root)
    try:
        import json

        config_path = _repo_root() / "config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("artifacts_root"), str):
                return Path(data["artifacts_root"])
    except Exception:
        pass
    return _repo_root() / "artifacts"


def _requested_resume_dir(config) -> Path | None:
    value = config.getoption("resume_run") or os.environ.get(RESUME_ENV)
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    return path if path.is_dir() else None


def _ensure_run(config) -> RunArtifacts:
    """Return this session's run, creating or reloading it on demand.

    A resumed session (after a reboot) reloads the previous run directory so
    evidence and per-item state stay in one place.
    """
    run = getattr(config, "_gui_run", None)
    if run is not None:
        return run
    root = _artifacts_root(config)
    root.mkdir(parents=True, exist_ok=True)
    if config._gui_resume_dir is not None:
        run = RunArtifacts.load(config._gui_resume_dir, root=root)
    else:
        run = RunArtifacts.create(
            root,
            metadata={
                "cwd": os.getcwd(),
                "argv": list(sys.argv),
                "env": {
                    "XDG_SESSION_TYPE": os.environ.get("XDG_SESSION_TYPE"),
                    "XDG_CURRENT_DESKTOP": os.environ.get("XDG_CURRENT_DESKTOP"),
                    "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
                    "DISPLAY": os.environ.get("DISPLAY"),
                },
            },
        )
    config._gui_run = run
    # From here on every completed test is recorded against this run, so a
    # later boot can skip it.
    config._gui_resume_dir = run.run_dir
    return run


def _finalize_run(config) -> None:
    run = getattr(config, "_gui_run", None)
    if run is None or getattr(config, "_gui_finalized", False):
        return
    config._gui_finalized = True
    try:
        plan = RetentionPlan((KeepLast(10), KeepFailures()))
        run.finalize(retention_plan=plan)
    except Exception:
        run.finalize()


def pytest_addoption(parser):
    parser.addoption(
        "--resume-run",
        action="store",
        default=None,
        metavar="DIR",
        help="resume a previous artifact run directory after a reboot",
    )


def pytest_configure(config):
    # A rebooted run reuses the previous run directory so artifacts and the
    # per-item state survive across the reboot.
    config._gui_resume_dir = _requested_resume_dir(config)
    config._gui_resume_requested = config._gui_resume_dir is not None
    # Track whether this is a resumed (background) run.
    config._gui_resumed = os.environ.get("GUI_TESTING_RESUMED") == "1"
    config._gui_reboot_items = []
    config._gui_reboot_setup = None
    config._gui_reboot_error = None
    config._gui_reboot_finished = False


def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = item.path.parts
        if "tests" not in parts:
            continue
        try:
            program = parts[parts.index("tests") + 1]
        except ValueError:
            continue
        if program in PROGRAMS:
            marker = program.replace("-", "_")
            item.add_marker(getattr(pytest.mark, marker))

    # Tests completed before the reboot are skipped in the resumed session.
    if config._gui_resume_dir is not None:
        completed = load_completed(config._gui_resume_dir)
        already_done = pytest.mark.skip(reason="completed before the last reboot")
        for item in items:
            if item.nodeid in completed:
                item.add_marker(already_done)

    # Avoid running destructive/state-changing tests by default on a dev box.
    if os.environ.get("RUN_DESTRUCTIVE_TESTS", "1") != "1":
        skip_destructive = pytest.mark.skip(
            reason="destructive/state-changing test skipped; set RUN_DESTRUCTIVE_TESTS=0 to skip"
        )
        for item in items:
            if item.get_closest_marker("destructive") or item.get_closest_marker("reboot"):
                item.add_marker(skip_destructive)

    # Remember which reboot tests will actually execute, so the session can
    # prepare autologin/resume only when it is needed.
    config._gui_reboot_items = [
        item.nodeid
        for item in items
        if item.get_closest_marker("reboot") and not item.get_closest_marker("skip")
    ]


def pytest_collection_finish(session):
    """Prepare autologin + resume iff a reboot test will actually execute."""
    config = session.config
    if getattr(config.option, "collectonly", False):
        return
    will_reboot = bool(config._gui_reboot_items)
    if not will_reboot and not config._gui_resume_requested and not getattr(config, "_gui_resumed", False):
        return

    run = _ensure_run(config)
    # On a resumed run the autologin config and resume unit are already in
    # place from the initial run, so skip the (privileged) setup step.
    if config._gui_resume_requested or getattr(config, "_gui_resumed", False):
        config._gui_reboot_setup = None
        return
    # If pytest.sh already did the privileged autologin setup, only install
    # the resume unit here (no sudo needed).
    if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
        try:
            from harness.reboot import install_resume_unit
            plan = install_resume_unit(
                run.run_dir,
                pytest_args=list(sys.argv[1:]),
                workdir=os.getcwd(),
                python=sys.executable,
            )
            config._gui_reboot_setup = None
            if not plan.installed:
                config._gui_reboot_error = plan.reason
        except Exception as error:
            config._gui_reboot_error = f"{type(error).__name__}: {error}"
        return
    try:
        config._gui_reboot_setup = prepare_reboot(
            run.run_dir,
            pytest_args=list(sys.argv[1:]),
            workdir=os.getcwd(),
            python=sys.executable,
        )
    except Exception as error:  # preparation is best-effort; never fail the run
        config._gui_reboot_error = f"{type(error).__name__}: {error}"


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    _finalize_run(config)
    setup = getattr(config, "_gui_reboot_setup", None)
    if os.environ.get("GUI_TESTING_KEEP_REBOOT_SETUP") == "1":
        return
    # Determine the user to clean up for.  On a resumed run, setup is None
    # (we skipped prepare_reboot), but cleanup is still needed.
    username = None
    if setup is not None:
        username = setup.username
    elif getattr(config, "_gui_resumed", False) or config._gui_resume_requested:
        from harness.reboot import detect_gui_user
        username = detect_gui_user()
    if username is None:
        return
    # A reboot kills this process, so this only runs once the run really
    # finishes (or is interrupted); restore the machine either way.
    finish_reboot(username=username)
    config._gui_reboot_finished = True
    # Clean up passwordless sudoers rule if pytest.sh created one.
    if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
        try:
            subprocess.run(
                ["sudo", "-n", "python3", "-m", "harness.reboot", "cleanup"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            pass


@pytest.fixture(scope="session")
def artifacts_root(pytestconfig):
    root = _artifacts_root(pytestconfig)
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def artifacts(pytestconfig):
    return _ensure_run(pytestconfig)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.passed:
        return
    run_dir = getattr(item.config, "_gui_resume_dir", None)
    if run_dir is None:
        return
    try:
        record_completed(run_dir, item.nodeid)
    except Exception:
        pass


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    setup = getattr(config, "_gui_reboot_setup", None)
    if setup is None:
        error = getattr(config, "_gui_reboot_error", None)
        if error:
            terminalreporter.write_sep("-", "reboot test setup")
            terminalreporter.write_line(f"preparation failed: {error}")
        return
    terminalreporter.write_sep("-", "reboot test setup")
    terminalreporter.write_line(setup.describe())
    if getattr(config, "_gui_reboot_finished", False):
        terminalreporter.write_line("autologin restored; resume unit removed")
