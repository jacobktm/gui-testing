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

# Cache the backlight device path discovered from sysfs scan.
_CACHED_BACKLIGHT: Optional[Path] = None


__all__ = [
    "BrightnessHandler",
    "brightness_up_to_max",
    "brightness_down_to_min",
    "get_backlight",
    "get_brightness",
    "get_max_brightness",
]


def get_backlight() -> Optional[Path]:
    """Return the best backlight device directory, or ``None``.

    Uses a module-level cache so repeated calls don't re-scan sysfs.
    """
    global _CACHED_BACKLIGHT
    if _CACHED_BACKLIGHT is not None and _CACHED_BACKLIGHT.exists():
        return _CACHED_BACKLIGHT

    base = Path("/sys/class/backlight")
    if not base.exists():
        return None
    candidates = [c for c in base.iterdir() if c.is_dir() or c.is_symlink()]
    if not candidates:
        return None

    def score(p: Path) -> int:
        s = 0
        if (p / "actual_brightness").exists():
            s += 10
        if p.is_symlink():
            s += 5
        try:
            mb = int((p / "max_brightness").read_text().strip())
            s += min(mb // 50, 5)
        except (OSError, ValueError):
            pass
        if "acpi_video" in p.name.lower():
            s -= 5
        return s

    result = max(candidates, key=score)
    _CACHED_BACKLIGHT = result
    return result


def _parse_system76_power_brightness() -> tuple[Optional[int], Optional[int]]:
    """Parse brightness from ``system76-power profile`` output.

    Returns (current, max) or (None, None) if no Backlight line is present
    or parsing fails.  If system76-power succeeds but has no Backlight line,
    it means there is no display brightness control by system76-power.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["system76-power", "profile"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None, None
        # If the command succeeds, look for a Backlight line.
        found_backlight_line = False
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.lower().startswith("backlight "):
                found_backlight_line = True
                # "Backlight acpi_video0: 5/19 = 26%"
                # or "Backlight nvidia_wmi_ec_backlight: 255/255 = 100%"
                if ":" in line:
                    after_colon = line.split(":", 1)[1].strip()
                    # "5/19 = 26%"
                    parts = after_colon.split()
                    if parts and "/" in parts[0]:
                        frac = parts[0]  # "5/19"
                        cur_str, max_str = frac.split("/", 1)
                        return int(cur_str), int(max_str)
        # Command succeeded but no Backlight line → no brightness control.
        if found_backlight_line is False and result.stdout.strip():
            return None, None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None, None


def get_brightness(backlight: Optional[Path] = None) -> Optional[int]:
    """Read the current brightness value.

    Uses ``system76-power profile`` output.  If system76-power succeeds
    but has no Backlight line, there is no display brightness control and
    None is returned.  Falls back to sysfs only if the CLI command fails.
    """
    cur, mx = _parse_system76_power_brightness()
    # If system76-power gave us a value, use it.
    if cur is not None:
        return cur
    # If system76-power succeeded but had no backlight line, don't fall
    # back to sysfs (no brightness control by system76-power).
    # We detect this by checking if the command succeeded at all.
    try:
        import subprocess
        result = subprocess.run(
            ["system76-power", "profile"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Command succeeded — if no backlight line, no brightness control.
            has_backlight = any(
                line.strip().lower().startswith("backlight ")
                for line in result.stdout.splitlines()
            )
            if not has_backlight:
                return None
    except (OSError, subprocess.SubprocessError):
        pass
    # Fall back to sysfs (CLI unavailable).
    bl = backlight or get_backlight()
    if bl is None:
        return None
    for name in ("actual_brightness", "brightness"):
        try:
            return int((bl / name).read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def get_max_brightness(backlight: Optional[Path] = None) -> Optional[int]:
    """Read the maximum brightness value.

    Uses ``system76-power profile`` output.  If system76-power succeeds
    but has no Backlight line, returns None (no brightness control).
    Falls back to sysfs only if the CLI command fails.
    """
    _, mx = _parse_system76_power_brightness()
    if mx is not None:
        return mx
    try:
        import subprocess
        result = subprocess.run(
            ["system76-power", "profile"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            has_backlight = any(
                line.strip().lower().startswith("backlight ")
                for line in result.stdout.splitlines()
            )
            if not has_backlight:
                return None
    except (OSError, subprocess.SubprocessError):
        pass
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

        tolerance = max(1, max_b // 20) if max_b else 1
        proc = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, text=True)
        try:
            presses = 0
            while presses < max_presses:
                current = self.current()
                if current is None:
                    break
                # Stop when within tolerance (EC backlights have coarse steps).
                if abs(current - target) <= tolerance:
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
        # The minimum is wherever brightness stops changing.
        c = self.current()
        if c is None:
            return False
        # Press down once more and check if it changed.
        prev = c
        proc = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, text=True)
        try:
            proc.stdin.write("key brightnessdown\n")
            proc.stdin.flush()
            import time
            time.sleep(self.delay)
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()
        new_val = self.current()
        return new_val is not None and new_val == prev

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

        Presses brightnessdown until the sysfs value stops changing (i.e.
        the hardware minimum is reached).  On some systems the minimum is
        not zero, so we detect the floor by watching for no change.

        Returns ``True`` if the value stabilised (stopped changing).
        """
        if self.backlight is None:
            return False

        prev = self.current()
        if prev is None:
            return False

        proc = subprocess.Popen(
            ["dotool"], stdin=subprocess.PIPE, text=True
        )
        try:
            presses = 0
            stable_count = 0
            last_val = prev
            while presses < max_presses:
                current = self.current()
                if current is None:
                    break
                for _ in range(steps_per_press):
                    proc.stdin.write("key brightnessdown\n")
                proc.stdin.flush()
                # Longer delay for EC backlights to update.
                time.sleep(max(self.delay, 0.3))
                presses += 1
                # Read multiple times to get the settled value.
                new_val = None
                for _ in range(3):
                    time.sleep(0.1)
                    v = self.current()
                    if v is not None:
                        new_val = v
                if new_val is None:
                    break
                # Track actual last value for stabilization check.
                if new_val == last_val:
                    stable_count += 1
                    if stable_count >= 5:
                        break
                else:
                    stable_count = 0
                last_val = new_val
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            proc.wait()

        return True


def brightness_up_to_max(delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: raise brightness to max and return success."""
    return BrightnessHandler(delay=delay).brightness_up_to_max(**kwargs)


def brightness_down_to_min(delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: lower brightness to min and return success."""
    return BrightnessHandler(delay=delay).brightness_down_to_min(**kwargs)


def brightness_set_percent(percent: int, delay: float = 0.15, **kwargs) -> bool:
    """Convenience wrapper: set brightness to a percentage and return success."""
    return BrightnessHandler(delay=delay).set_brightness_percent(percent, **kwargs)
