"""Brightness handling for the harness.

Unlike :mod:`handlers.brightness`, which writes directly to sysfs (and
therefore needs root), this module drives the screen's brightness keys
through dotool and reads the resulting value back from sysfs.  It can be
used without sudo.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

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
