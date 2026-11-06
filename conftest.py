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

    # The report and the run status are driven by the pytest outcomes
    # themselves.  completed.json holds every test that reached a call-phase
    # verdict on *any* boot of this run; _gui_pytest_results holds this boot's
    # verdicts for every phase (including tests re-reported from the resume
    # override, whose verdicts re-enter via the completed ledger).
    results: dict[str, str] = {}
    try:
        results.update(load_completed(run.run_dir))
    except Exception as error:
        print(f"report: could not load completed ledger: {error}", flush=True)
    results.update(getattr(config, "_gui_pytest_results", {}))
    collected = list(getattr(config, "_gui_collected_nodeids", []))
    not_run = [nodeid for nodeid in collected if nodeid not in results]

    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for verdict in results.values():
        counts[verdict] = counts.get(verdict, 0) + 1
    counts["not_run"] = len(not_run)
    unknown_items = sum(
        1 for entry in run.manifest.tests
        if entry.get("status", "unknown") == "unknown"
    )

    # A run only "passed" if every collected test actually ran and none
    # failed; leftover unknown evidence, un-run tests, or an all-skipped
    # session are all "unknown", which KeepFailures treats as non-passing.
    if counts["failed"] or counts["error"]:
        run_status = "failed"
    elif counts["not_run"] or unknown_items or not (counts["passed"] or counts["failed"]):
        run_status = "unknown"
    else:
        run_status = "passed"

    run.manifest.metadata["pytest_results"] = results
    run.manifest.metadata["pytest_not_run"] = not_run
    try:
        plan = RetentionPlan((KeepLast(10), KeepFailures()))
        run.finalize(status=run_status, summary=counts, retention_plan=plan)
    except Exception as error:
        print(f"report: finalize failed ({error}); retrying without retention", flush=True)
        try:
            run.finalize(status=run_status, summary=counts)
        except Exception as error2:
            print(f"report: finalize failed entirely: {error2}", flush=True)
    try:
        from harness.report import ReportWriter
        ReportWriter(run).write_text()
        ReportWriter(run).archive()
    except Exception as error:
        print(f"report: writing/archiving failed: {error}", flush=True)


def pytest_addoption(parser):
    parser.addoption(
        "--resume-run",
        action="store",
        default=None,
        metavar="DIR",
        help="resume a previous artifact run directory after a reboot",
    )


def pytest_configure(config):
    # Keep the screen from blanking/locking for the duration of the run.
    # Saving is idempotent so a resumed run (fresh process after a reboot)
    # re-applies the settings without clobbering the user's originals.
    try:
        from harness.reboot.idle import disable_idle, save_idle_state

        save_idle_state()
        report = disable_idle()
        config._gui_idle_report = report
        for err in report["errors"]:
            print(f"[idle] ERROR: {err}", flush=True)
        if not report["applied"] or report["readback_ok"] is False:
            print("[idle] WARNING: idle protection is NOT active — GUI tests may hit a locked screen", flush=True)
    except Exception as error:  # never fail a run over this
        print(f"[idle] setup failed: {type(error).__name__}: {error}", flush=True)

    # Cache display geometry early (before any GUI tests run).
    # Force re-detection on resumed runs (after reboot).
    try:
        from harness.gui.coords import cache_display_geometry
        force = os.environ.get("GUI_TESTING_RESUMED") == "1"
        cache_display_geometry(force=force)
    except Exception:
        pass
    # Pre-grant screenshot permission on COSMIC to avoid dialog during tests.
    try:
        subprocess.run(
            [
                "busctl", "--user", "call",
                "org.freedesktop.impl.portal.PermissionStore",
                "/org/freedesktop/impl/portal/PermissionStore",
                "org.freedesktop.impl.portal.PermissionStore",
                "SetPermission",
                "sbssas", "screenshot", "false",
                "com.system76.CosmicScreenshot", "screenshot", "1", "granted",
            ],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass

    # Save original graphics mode before tests run (for cleanup restore).
    try:
        from handlers.system76_power import System76Power
        from handlers.system76_power.power_state import save_original_graphics_mode_from
        h = System76Power()
        save_original_graphics_mode_from(h)
    except Exception:
        pass

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
    # nodeid -> verdict (passed/failed/skipped/error) for this boot's runs,
    # the input to test_report.txt and the run status.
    config._gui_pytest_results = {}
    config._gui_collected_nodeids = []


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

    # Tests completed before the reboot are tracked for outcome override.
    # Their test body is replaced with a no-op so they don't re-run, and
    # their result is overridden to passed/failed in pytest_runtest_makereport.
    if config._gui_resume_dir is not None:
        completed = load_completed(config._gui_resume_dir)
        for item in items:
            if item.nodeid in completed:
                item._completed_outcome = completed[item.nodeid]
                # Replace test body with no-op to avoid side effects.
                item.runtest = lambda: None

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

    # Run the idle-guard test first: if idle/lock protection never took
    # effect, nothing GUI later in the run can be trusted, and a reboot test
    # must not start only to strand a locked session mid-multi-boot-run.
    # Run screenshot permission test next (grants permission for all later
    # screenshots).
    # Run graphics power toggle tests last (they can leave the GPU in a bad
    # state that affects subsequent tests).
    def _sort_key(item):
        name = getattr(item, "name", "") or ""
        if "idle_protection" in name:
            return -2
        if "screenshot_permission" in name:
            return -1
        if "graphics_power" in name:
            return 1
        return 0

    items.sort(key=_sort_key)
    # Remember what this boot collected so the report can flag tests that
    # never ran (interrupted session, killed reboot, collection gaps).
    config._gui_collected_nodeids = [item.nodeid for item in items]


def pytest_collection_finish(session):
    """Prepare autologin + resume iff a reboot test will actually execute."""
    config = session.config
    if getattr(config.option, "collectonly", False):
        return
    will_reboot = bool(config._gui_reboot_items)
    if not will_reboot and not config._gui_resume_requested and not getattr(config, "_gui_resumed", False):
        return

    run = _ensure_run(config)
    # Refresh the "run in progress" marker on every boot of a multi-boot run
    # (this hook runs on resumed runs too), so the boot-time recovery unit
    # leaves the harness setup alone while the run is live.
    try:
        from harness.reboot.recovery import mark_run_active
        mark_run_active(run.run_dir)
    except Exception as error:
        print(f"GUI testing: run marker failed: {error}", flush=True)
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
    # Restore idle/lock settings
    try:
        from harness.reboot import restore_idle
        restore_idle()
    except Exception:
        pass
    # Restore brightness to max (tests may leave it at min).
    try:
        from harness.brightness import BrightnessHandler
        BrightnessHandler().brightness_up_to_max()
    except Exception:
        pass
    setup = getattr(config, "_gui_reboot_setup", None)
    if os.environ.get("GUI_TESTING_KEEP_REBOOT_SETUP") == "1":
        return
    # Determine the user to clean up for.  On a resumed run, setup is None
    # (we skipped prepare_reboot), but cleanup is still needed.
    username = None
    if setup is not None:
        username = setup.username
    elif (
        getattr(config, "_gui_resumed", False)
        or config._gui_resume_requested
        or os.environ.get("GUI_TESTING_SETUP_DONE") == "1"
    ):
        # Resumed runs skip prepare_reboot, and a pytest.sh run did the setup
        # out-of-process — either way, resolve the user and clean up anyway.
        from harness.reboot import detect_gui_user
        username = detect_gui_user()
    if username is None:
        return
    # A reboot kills this process, so this only runs once the run really
    # finishes (or is interrupted); restore the machine either way.
    # revoke_sudoers=False: the final reboot below still needs the grant;
    # it is removed after the last reboot attempt, and the boot-time recovery
    # unit is the backstop if this process dies to that reboot.
    print("CLEANUP: calling finish_reboot", flush=True)
    try:
        finish_reboot(username=username, revoke_sudoers=False)
        print("CLEANUP: finish_reboot done", flush=True)
    except Exception as e:
        print(f"CLEANUP: finish_reboot EXCEPTION: {e}", flush=True)
        import traceback
        traceback.print_exc()
    except BaseException as e:
        print(f"CLEANUP: finish_reboot BASE EXCEPTION: {e}", flush=True)
        import traceback
        traceback.print_exc()
    config._gui_reboot_finished = True

    # From here on no run is live: drop the marker *before* any of the reboots
    # below, so the boot-time recovery unit finishes the teardown (sudoers
    # revoke included) if the final reboot kills this process first.
    try:
        from harness.reboot.recovery import clear_run_active
        clear_run_active()
    except Exception:
        pass

    # Restore original graphics mode last thing before final reboot.
    try:
        from handlers.system76_power import System76Power
        from handlers.system76_power.power_state import restore_original_graphics_mode
        h = System76Power()
        if restore_original_graphics_mode(h):
            from harness.reboot.system import reboot, wait_for_boot
            reboot(None)
            wait_for_boot(None)
    except Exception:
        pass

    # Final reboot after cleanup (signals test completion to the user).
    # Try multiple methods since sudoers may already be gone.
    if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
        print("CLEANUP: triggering final reboot", flush=True)
        rebooted = False
        for cmd in (["systemctl", "reboot"], ["sudo", "-n", "systemctl", "reboot"], ["sudo", "-n", "reboot", "-f"], ["reboot"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                print(f"CLEANUP: reboot {cmd} rc={r.returncode} stderr={r.stderr.strip()}", flush=True)
                if r.returncode == 0:
                    rebooted = True
                    break
            except Exception as e:
                print(f"CLEANUP: reboot {cmd} exception: {e}", flush=True)
        # Give the reboot a moment to start.
        import time
        time.sleep(5)

    # Clean up passwordless sudoers rule if pytest.sh created one.
    if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
        print("CLEANUP: removing sudoers rule", flush=True)
        try:
            from harness.reboot.helper import priv_cleanup_sudoers
            print(f"CLEANUP: sudoers cleanup: {priv_cleanup_sudoers()}", flush=True)
        except Exception as e:
            print(f"CLEANUP: sudoers cleanup exception: {e}", flush=True)


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

    # Track how many manifest entries existed before this test (for status update).
    if call.when == "setup":
        run = getattr(item.config, "_gui_run", None)
        if run is not None:
            item._manifest_count_before = len(run.manifest.tests)

    # Override outcome for tests completed in a previous run.
    stored_outcome = getattr(item, "_completed_outcome", None)
    if stored_outcome is not None and report.when == "call":
        if stored_outcome == "passed":
            report.outcome = "passed"
        else:
            report.outcome = "failed"
            if not report.longrepr:
                report.longrepr = "Failed in previous run before reboot"

    # Feed the per-test verdicts that drive test_report.txt and the run
    # status: the worst outcome across setup/call/teardown wins.
    verdicts = getattr(item.config, "_gui_pytest_results", None)
    if verdicts is not None:
        if report.when == "call":
            recorded = report.outcome
        elif report.outcome == "failed":
            recorded = "error"
        elif report.outcome == "skipped":
            recorded = "skipped"
        else:
            recorded = None
        if recorded in ("passed", "failed", "skipped", "error"):
            severity = {"passed": 1, "skipped": 2, "failed": 3, "error": 3}
            previous = verdicts.get(item.nodeid)
            if previous is None or severity[recorded] >= severity[previous]:
                verdicts[item.nodeid] = recorded

    # Record completed tests with their actual outcome.
    if report.when == "call" and report.outcome in ("passed", "failed") and stored_outcome is None:
        run_dir = getattr(item.config, "_gui_resume_dir", None)
        if run_dir is not None:
            try:
                record_completed(run_dir, item.nodeid, outcome=report.outcome)
            except Exception as error:
                print(f"GUI testing: could not record completion: {error}", flush=True)
        # Stamp manifest entries *created during this test* with its outcome:
        # those belong to this test's workflow.  Entries that already existed
        # before the test started belong to other tests (or earlier boots of
        # this run) and must never be stamped with this test's outcome —
        # that fabricated passes for tests that never completed.
        try:
            run = getattr(item.config, "_gui_run", None)
            if run is not None:
                before = getattr(item, "_manifest_count_before", 0)
                stamped = False
                for entry in run.manifest.tests[before:]:
                    if entry.get("status", "unknown") == "unknown":
                        entry["status"] = report.outcome
                        stamped = True
                if stamped:
                    run._save()
        except Exception as error:
            print(f"GUI testing: could not stamp manifest entries: {error}", flush=True)


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
