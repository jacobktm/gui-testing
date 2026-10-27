"""Screenshot backends and capture rules.

Capture modes:
- ``file``: the backend writes to the exact destination path.
- ``landing``: the backend writes to its own directory; the newest file
  produced after the trigger is moved to the destination and renamed.

Files are always renamed on ingest, so backend filenames do not matter.

GNOME multi-display captures are scaled globally by the highest monitor
scale. Crop every monitor using that maximum scale, including monitors that
report scale 1, so mixed-scale layouts behave the same on Pop!_OS 22.04 and
Ubuntu 26.04.

COSMIC multi-display captures stay in logical coordinates, so its crop boxes
must not be scaled. Single-display captures are never cropped. ``crop_scale``
marks whether crop boxes are multiplied by the highest detected scale.

``crop_displays`` writes one crop per display and records ``active_index`` so
the display under test is explicit while every other display remains available
as an artifact for debugging.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import get_screenshot_tool
from ..dotool import send_keys
from ..imageutils import crop as crop_image
from ..imageutils import scale_crop_box

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})

__all__ = [
    "SCREENSHOT_TOOLS",
    "DisplayCrop",
    "DisplayCrops",
    "Screenshot",
    "ScreenshotError",
    "capture",
    "grant_screenshot_permission",
    "crop_active_display",
    "crop_displays",
    "crop_to_monitor",
    "monitor_crop_box",
    "resolve_screenshot_tool",
]

SCREENSHOT_TOOLS = {
    "cosmic-screenshot": {
        "cmd": ["cosmic-screenshot", "--interactive=false"],
        "mode": "landing",
        "landing": "~/Pictures",
        "crop_scale": False,
    },
    "gnome-dotool": {
        "keys": [
            "keydown leftshift",
            "key print",
            "keyup leftshift",
        ],
        "mode": "landing",
        "landing": "~/Pictures/Screenshots",
        "crop_scale": True,
    },
}


class ScreenshotError(RuntimeError):
    """Raised when a screenshot cannot be captured or read."""


@dataclass(frozen=True)
class Screenshot:
    path: Path
    width: int
    height: int
    tool: str
    crop_scale: bool
    captured_at: datetime
    source: Path | None = None
    source_name: str | None = None
    landing: Path | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "width": self.width,
            "height": self.height,
            "crop_scale": self.crop_scale,
            "source": self.source_name,
            "captured_at": self.captured_at.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class DisplayCrop:
    index: int
    path: Path
    origin: tuple[int, int]
    width: int
    height: int

    def metadata(self) -> dict[str, Any]:
        return {
            "display": self.index,
            "file": self.path.name,
            "origin": list(self.origin),
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class DisplayCrops:
    displays: tuple[DisplayCrop, ...]
    active_index: int

    @property
    def active(self) -> DisplayCrop:
        return self.displays[self.active_index]

    def metadata(self) -> dict[str, Any]:
        return {
            "active_display": self.active_index,
            "displays": [display.metadata() for display in self.displays],
        }


def resolve_screenshot_tool(tool: str | None = None) -> str:
    if tool:
        tool = str(tool).strip()
        if tool in SCREENSHOT_TOOLS:
            return tool
        raise ScreenshotError(f"unsupported screenshot tool: {tool!r}")

    configured = get_screenshot_tool()
    if configured and configured in SCREENSHOT_TOOLS:
        return configured

    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "cosmic" in desktop:
        return "cosmic-screenshot"
    if "gnome" in desktop:
        return "gnome-dotool"
    raise ScreenshotError(
        "no supported screenshot tool configured; run setup.sh or pass tool="
    )


def grant_screenshot_permission() -> bool:
    """Pre-grant screenshot permission on COSMIC (avoids dialog during tests).

    Uses the xdg-desktop-portal permission store D-Bus interface.
    Returns True if the permission was set successfully.
    """
    try:
        result = subprocess.run(
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
        return result.returncode == 0
    except Exception:
        return False



def capture(
    destination: Path | str,
    *,
    tool: str | None = None,
    timeout: float = 10.0,
    poll_interval: float = 0.1,
) -> Screenshot:
    destination = Path(destination)
    if destination.exists():
        raise ScreenshotError(f"destination already exists: {destination}")

    tool = resolve_screenshot_tool(tool)
    config = SCREENSHOT_TOOLS[tool]
    destination.parent.mkdir(parents=True, exist_ok=True)

    mode = config.get("mode")
    source = None
    landing = None

    if mode == "file":
        _run_command(list(config["cmd"]) + [str(destination)], timeout)
        if not destination.is_file():
            raise ScreenshotError(f"screenshot was not written to {destination}")
        captured_at = datetime.now(tz=timezone.utc)
    elif mode == "landing":
        landing = Path(config["landing"]).expanduser()
        landing.mkdir(parents=True, exist_ok=True)
        baseline = _snapshot(landing)
        since = time.time()
        _trigger(config, timeout)
        source = _wait_for_capture(landing, baseline, since, timeout, poll_interval)
        shutil.move(str(source), str(destination))
        captured_at = datetime.now(tz=timezone.utc)
    else:
        raise ScreenshotError(f"unsupported capture mode for {tool!r}: {mode!r}")

    width, height = _dimensions(destination)
    return Screenshot(
        path=destination,
        width=width,
        height=height,
        tool=tool,
        crop_scale=bool(config.get("crop_scale", False)),
        captured_at=captured_at,
        source=source,
        source_name=source.name if source is not None else destination.name,
        landing=landing,
    )


def _load_monitors(
    monitors: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if monitors is not None:
        return monitors
    try:
        from ..display import get_monitors

        return get_monitors()
    except Exception as exc:
        raise ScreenshotError(f"could not detect monitors: {exc}") from exc


def monitor_crop_box(
    monitor: dict[str, Any],
    monitors: list[dict[str, Any]],
    *,
    crop_scale: bool,
) -> tuple[tuple[int, int], int, int]:
    """Return the pixel crop box for ``monitor`` in a multi-display capture.

    ``scale_crop_box`` is applied before cropping, never the other way round.
    GNOME captures use the highest scale across all monitors; COSMIC captures
    stay in logical coordinates.
    """
    if not monitors:
        raise ScreenshotError("no monitors detected")
    scale = 1.0
    if crop_scale:
        scale = max(float(item.get("scale", 1)) for item in monitors)
    origin = (int(monitor["x"]), int(monitor["y"]))
    width = int(monitor["width"])
    height = int(monitor["height"])
    if scale != 1:
        origin, width, height = scale_crop_box(origin, width, height, scale)
    return origin, width, height


def crop_to_monitor(
    screenshot: Screenshot,
    output_path: Path | str,
    *,
    monitor_index: int = 0,
    monitors: list[dict[str, Any]] | None = None,
) -> Path:
    """Crop a capture to one monitor, or copy it unchanged on a single display.

    The monitor layout is queried lazily so capturing does not require GTK.
    """
    output_path = Path(output_path)
    monitors = _load_monitors(monitors)
    if not monitors:
        raise ScreenshotError("no monitors detected")

    if len(monitors) == 1:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screenshot.path, output_path)
        return output_path

    if not 0 <= monitor_index < len(monitors):
        raise ScreenshotError(
            f"monitor index {monitor_index} out of range for {len(monitors)} displays"
        )

    origin, width, height = monitor_crop_box(
        monitors[monitor_index],
        monitors,
        crop_scale=screenshot.crop_scale,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        crop_image(screenshot.path, origin, width, height, output_path)
    except (OSError, ValueError) as exc:
        raise ScreenshotError(
            f"could not crop {screenshot.path} to monitor {monitor_index}: {exc}"
        ) from exc
    return output_path


def _resolve_active_index(
    monitors: list[dict[str, Any]],
    active_index: int | None,
) -> int:
    if len(monitors) == 1:
        if active_index not in (None, 0):
            raise ScreenshotError(
                f"active display {active_index} out of range for 1 display"
            )
        return 0

    if active_index is not None:
        if not 0 <= active_index < len(monitors):
            raise ScreenshotError(
                f"active display {active_index} out of range "
                f"for {len(monitors)} displays"
            )
        return active_index

    try:
        from ..display import get_display_index

        index = get_display_index(monitors)
    except Exception as exc:
        raise ScreenshotError(f"could not determine active display: {exc}") from exc
    if index is None:
        raise ScreenshotError(
            "could not determine active display; pass active_index explicitly"
        )
    return index


def crop_active_display(
    screenshot: Screenshot,
    output_path: Path | str,
    *,
    active_index: int | None = None,
    monitors: list[dict[str, Any]] | None = None,
    save_all: bool = True,
    all_dir: Path | str | None = None,
) -> DisplayCrop:
    """Crop the display containing the pointer/window under test.

    By default every display is cropped and saved as artifacts (``displays/``)
    for validation/troubleshooting; the active crop is copied to ``output_path``
    and returned.
    """
    monitors = _load_monitors(monitors)
    if not monitors:
        raise ScreenshotError("no monitors detected")

    active_index = _resolve_active_index(monitors, active_index)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if save_all or len(monitors) > 1:
        if all_dir is None:
            all_dir = output_path.parent / "displays"
        crops = crop_displays(
            screenshot,
            all_dir,
            active_index=active_index,
            monitors=monitors,
        )
        active = crops.active
        if active.path != output_path:
            shutil.copy2(active.path, output_path)

        try:
            metadata = {
                "screenshot": str(screenshot.path),
                "source_name": screenshot.source_name,
                "tool": screenshot.tool,
                "crop_scale": screenshot.crop_scale,
                "active_display": active_index,
                "monitors": monitors,
                "captured_at": screenshot.captured_at.isoformat().replace(
                    "+00:00", "Z"
                ),
            }
            import json

            (Path(all_dir) / "metadata.json").write_text(
                json.dumps(metadata, indent=2)
            )
        except OSError:
            pass

        return DisplayCrop(
            index=active.index,
            path=output_path,
            origin=active.origin,
            width=active.width,
            height=active.height,
        )

    # Single display, no need to persist all crops
    if len(monitors) == 1:
        origin = (0, 0)
        width = screenshot.width
        height = screenshot.height
        shutil.copy2(screenshot.path, output_path)
        return DisplayCrop(
            index=0,
            path=output_path,
            origin=origin,
            width=width,
            height=height,
        )

    # Fallback
    monitor = monitors[active_index]
    origin, width, height = monitor_crop_box(
        monitor,
        monitors,
        crop_scale=screenshot.crop_scale,
    )
    try:
        crop_image(screenshot.path, origin, width, height, output_path)
    except (OSError, ValueError) as exc:
        raise ScreenshotError(
            f"could not crop {screenshot.path} to active display {active_index}: {exc}"
        ) from exc
    return DisplayCrop(
        index=active_index,
        path=output_path,
        origin=origin,
        width=width,
        height=height,
    )


def crop_displays(
    screenshot: Screenshot,
    output_dir: Path | str,
    *,
    active_index: int | None = None,
    monitors: list[dict[str, Any]] | None = None,
) -> DisplayCrops:
    """Crop every display and mark the one the test should use.

    All displays are saved as artifacts for validation/troubleshooting;
    ``active_index`` identifies which one contains the window under the mouse.
    """
    monitors = _load_monitors(monitors)
    if not monitors:
        raise ScreenshotError("no monitors detected")

    active_index = _resolve_active_index(monitors, active_index)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    crops: list[DisplayCrop] = []

    if len(monitors) == 1:
        path = output_dir / "display-0.png"
        shutil.copy2(screenshot.path, path)
        crops.append(
            DisplayCrop(
                index=0,
                path=path,
                origin=(0, 0),
                width=screenshot.width,
                height=screenshot.height,
            )
        )
        return DisplayCrops(tuple(crops), active_index)

    for index, monitor in enumerate(monitors):
        origin, width, height = monitor_crop_box(
            monitor,
            monitors,
            crop_scale=screenshot.crop_scale,
        )
        path = output_dir / f"display-{index}.png"
        try:
            crop_image(screenshot.path, origin, width, height, path)
        except (OSError, ValueError) as exc:
            raise ScreenshotError(
                f"could not crop {screenshot.path} to display {index}: {exc}"
            ) from exc
        crops.append(
            DisplayCrop(
                index=index,
                path=path,
                origin=origin,
                width=width,
                height=height,
            )
        )

    return DisplayCrops(tuple(crops), active_index)


def _trigger(config: dict[str, Any], timeout: float) -> None:
    if "cmd" in config:
        _run_command(list(config["cmd"]), timeout)
        return
    keys = config.get("keys")
    if keys:
        text = "\n".join(keys) if isinstance(keys, (list, tuple)) else str(keys)
        try:
            send_keys(text)
        except OSError as exc:
            raise ScreenshotError(f"could not trigger screenshot: {exc}") from exc
        return
    raise ScreenshotError("screenshot backend has no command or keys")


def _run_command(cmd: list[str], timeout: float) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ScreenshotError(f"screenshot command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise ScreenshotError(
            f"screenshot command failed ({exc.returncode}): {stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotError(
            f"screenshot command timed out after {timeout}s"
        ) from exc
    except OSError as exc:
        raise ScreenshotError(f"could not run screenshot command: {exc}") from exc


def _snapshot(directory: Path) -> dict[str, float]:
    state: dict[str, float] = {}
    try:
        children = list(directory.iterdir())
    except OSError:
        return state
    for child in children:
        if not child.is_file():
            continue
        try:
            state[child.name] = child.stat().st_mtime
        except OSError:
            continue
    return state


def _newest_candidate(
    directory: Path,
    baseline: dict[str, float],
    since: float,
) -> Path | None:
    newest = None
    newest_key = None
    try:
        children = list(directory.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_file() or child.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        if child.name in baseline and stat.st_mtime <= baseline[child.name]:
            continue
        if stat.st_mtime < since - 2.0:
            continue
        key = (stat.st_mtime, child.name)
        if newest_key is None or key > newest_key:
            newest = child
            newest_key = key
    return newest


def _wait_for_capture(
    directory: Path,
    baseline: dict[str, float],
    since: float,
    timeout: float,
    poll_interval: float,
) -> Path:
    deadline = time.monotonic() + timeout
    candidate = None
    candidate_size = None
    while time.monotonic() < deadline:
        newest = _newest_candidate(directory, baseline, since)
        if newest is None:
            candidate = None
            candidate_size = None
        else:
            try:
                size = newest.stat().st_size
            except OSError:
                size = 0
            if size > 0 and newest == candidate and size == candidate_size:
                return newest
            candidate = newest
            candidate_size = size
        time.sleep(poll_interval)
    raise ScreenshotError(
        f"no new screenshot appeared in {directory} within {timeout}s"
    )


def _dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception as exc:
        raise ScreenshotError(f"could not read screenshot {path}: {exc}") from exc
