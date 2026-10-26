"""Brightness handling for the harness.

Drives the screen's brightness keys through dotool and reads the
resulting value back from sysfs.  Does not need sudo.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

STATE_PATH = Path.home() / ".local/share/gui-testing/brightness.json"


__all__ = [
    "BrightnessHandler",
    "brightness_up_to_max",
    "brightness_down_to_min",
    "get_backlight",
    "get_brightness",
    "get_max_brightness",
]


def get_backlight() -> Optional[Path]:
    """Return the first backlight device directory, or ``None``."""
    base = Path("/sys/class/backlight")
    if not base.exists():
        return None
    for child in sorted(base.iterdir()):
        if child.is_dir():
            return child
    return None


def get_brightness(backlight: Optional[Path] = None) -> Optional[int]:
    """Read the current brightness value from sysfs."""
    bl = backlight or get_backlight()
    if bl is None:
        return None
    try:
        return int((bl / "brightness").read_text().strip())
    except (OSError, ValueError):
        return None


def get_max_brightness(backlight: Optional[Path] = None) -> Optional[int]:
    """Read the maximum brightness value from sysfs."""
    bl = backlight or get_backlight()
    if bl is None:
        return None
    try:
        return int((bl / "max_brightness").read_text().strip())
    except (OSError, ValueError):
        return None


class BrightnessHandler:
    """Drive screen brightness via dotool keys, reading state from sysfs."""

    def __init__(self, backlight: Optional[Path] = None, delay: float = 0.15):
        self.backlight = backlight or get_backlight()
        self.delay = delay

    def current(self) -> Optional[int]:
        return get_brightness(self.backlight)

    def maximum(self) -> Optional[int]:
        return get_max_brightness(self.backlight)

    def save_state(self, path=None) -> "Path | None":
        """Save current brightness to a JSON file (no sudo needed)."""
        if path is None:
            path = STATE_PATH
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            state = {"brightness": self.current(), "max_brightness": self.maximum()}
            path.write_text(json.dumps(state))
            return path
        except Exception:
            return None

    def restore_state(self, path=None) -> bool:
        """Restore brightness from a saved JSON file using dotool keys."""
        if path is None:
            path = STATE_PATH
        path = Path(path)
        if not path.exists():
            return False
        try:
            state = json.loads(path.read_text())
            target = state.get("brightness")
            if target is None:
                return False
            return self.set_brightness_value(target)
        except Exception:
            return False
        return False

    def set_brightness_value(self, target: int, *, max_presses: int = 200) -> bool:
        """Set brightness to an absolute value using dotool up/down keys.

        Reads current brightness from sysfs after each key press.  Presses
        brightnessup or brightnessdown until the reported value reaches (or
        crosses) ``target``.  Returns ``True`` if the final value is within
        one key-step of ``target``.
        """
        if self.backlight is None:
            return False
        max_b = self.maximum()
        if max_b is None:
            return False
        target = max(0, min(target, max_b))

        proc = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, text=True)
        try:
            presses = 0
            while presses < max_presses:
                current = self.current()
                if current is None:
                    break
                if current == target:
                    break
                if current < target:
                    proc.stdin.write("key brightnessup\n")
                else:
                    proc.stdin.write("key brightnessdown\n")
                proc.stdin.flush()
                time.sleep(self.delay)
                presses += 1
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()

        current = self.current()
        return current is not None and abs(current - target) <= max(1, max_b // 20)

    def set_brightness_percent(self, percent: int, *, max_presses: int = 200) -> bool:
        """Set brightness to a percentage (0-100) using dotool keys."""
        max_b = self.maximum()
        if max_b is None:
            return False
        percent = max(0, min(100, percent))
        target = int(max_b * percent / 100)
        return self.set_brightness_value(target, max_presses=max_presses)

    def is_at_max(self) -> bool:
        c = self.current()
        m = self.maximum()
        return c is not None and m is not None and c >= m

    def is_at_min(self) -> bool:
        c = self.current()
        return c is not None and c <= 0

    def brightness_up_to_max(
        self,
        *,
        max_presses: int = 200,
        steps_per_press: int = 1,
    ) -> bool:
        """Raise brightness to maximum using dotool ``brightnessup`` keys.

        A single dotool process is kept open for the whole loop; after each
        press (or batch of presses) we sleep ``self.delay`` seconds and then
        re-read the value from sysfs.  The loop stops as soon as the reported
        brightness reaches (or exceeds) the hardware maximum, or after
        ``max_presses`` iterations.

        Returns ``True`` if the maximum was reached.
        """
        if self.backlight is None:
            return False
        max_b = self.maximum()
        if max_b is None:
            return False

        proc = subprocess.Popen(
            ["dotool"], stdin=subprocess.PIPE, text=True
        )
        try:
            presses = 0
            while presses < max_presses:
                current = self.current()
                if current is None or current >= max_b:
                    break
                for _ in range(steps_per_press):
                    proc.stdin.write("key brightnessup\n")
                proc.stdin.flush()
                time.sleep(self.delay)
                presses += 1
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()

        current = self.current()
        return current is not None and current >= max_b

    def brightness_down_to_min(
        self,
        *,
        max_presses: int = 200,
        steps_per_press: int = 1,
    ) -> bool:
        """Lower brightness to minimum using dotool ``brightnessdown`` keys.

        Returns ``True`` if brightness reached (or went below) zero.
        """
        if self.backlight is None:
            return False

        proc = subprocess.Popen(
            ["dotool"], stdin=subprocess.PIPE, text=True
        )
        try:
            presses = 0
            while presses < max_presses:
                current = self.current()
                if current is None or current <= 0:
                    break
                for _ in range(steps_per_press):
                    proc.stdin.write("key brightnessdown\n")
                proc.stdin.flush()
                time.sleep(self.delay)
                presses += 1
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()

        current = self.current()
        return current is not None and current <= 0


def brightness_up_to_max(delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: raise brightness to max and return success."""
    return BrightnessHandler(delay=delay).brightness_up_to_max(**kwargs)


def brightness_down_to_min(delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: lower brightness to min and return success."""
    return BrightnessHandler(delay=delay).brightness_down_to_min(**kwargs)


def brightness_set_percent(percent: int, delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: set brightness to a percentage and return success."""
    return BrightnessHandler(delay=delay).set_brightness_percent(percent, **kwargs)
