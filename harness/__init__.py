"""GUI automation test harness.

Submodules are exposed lazily so ``import harness`` stays cheap and does not
pull in optional/system dependencies (GTK, ollama) until a submodule is used::

    import harness
    harness.display.get_monitors()
    harness.artifacts.Manifest(...)

Equivalent explicit form::

    from harness.display import get_monitors
    from harness.artifacts import Manifest
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__all__ = [
    "artifacts",
    "brightness",
    "config",
    "display",
    "dotool",
    "gui",
    "imageutils",
    "ollama_client",
    "reboot",
    "report",
    "screenshots",
]

if TYPE_CHECKING:
    from . import (
        artifacts,
        brightness,
        config,
        display,
        dotool,
        gui,
        imageutils,
        ollama_client,
        reboot,
        report,
        screenshots,
    )


def __getattr__(name: str):
    if name in __all__:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
