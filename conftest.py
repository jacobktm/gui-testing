import os
from pathlib import Path

import pytest

from harness.artifacts import KeepFailures, KeepLast, RetentionPlan, RunArtifacts

PROGRAMS = ["system76-power"]

__all__ = [
    "PROGRAMS",
    "pytest_collection_modifyitems",
    "artifacts",
    "artifacts_root",
]


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

    # Avoid running destructive/state-changing tests by default on a dev box
    if os.environ.get("RUN_DESTRUCTIVE_TESTS") == "1":
        return
    skip_destructive = pytest.mark.skip(
        reason="destructive/state-changing test skipped; set RUN_DESTRUCTIVE_TESTS=1 to run"
    )
    for item in items:
        if item.get_closest_marker("destructive") or item.get_closest_marker("reboot"):
            item.add_marker(skip_destructive)


@pytest.fixture(scope="session")
def artifacts_root(pytestconfig):
    root = _artifacts_root(pytestconfig)
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(scope="session")
def artifacts(artifacts_root):
    run = RunArtifacts.create(
        artifacts_root,
        metadata={
            "cwd": os.getcwd(),
            "env": {
                "XDG_SESSION_TYPE": os.environ.get("XDG_SESSION_TYPE"),
                "XDG_CURRENT_DESKTOP": os.environ.get("XDG_CURRENT_DESKTOP"),
                "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
                "DISPLAY": os.environ.get("DISPLAY"),
            },
        },
    )
    yield run
    try:
        plan = RetentionPlan((KeepLast(10), KeepFailures()))
        run.finalize(retention_plan=plan)
    except Exception:
        run.finalize()
