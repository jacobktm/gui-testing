from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["Brightness"]


DEFAULT_STATE_PATH = Path("/var/lib/gui-testing/brightness.json")
USER_STATE_PATH = Path.home() / ".local/share/gui-testing/brightness.json"


class Brightness:
    def __init__(self):
        self.backlight = self._find_backlight()

    def _find_backlight(self):
        base = Path("/sys/class/backlight")
        if not base.exists():
            return None
        for child in base.iterdir():
            if child.is_dir():
                return child
        return None

    def get_brightness(self):
        if not self.backlight:
            return None
        try:
            return int((self.backlight / "brightness").read_text().strip())
        except Exception:
            return None

    def get_max_brightness(self):
        if not self.backlight:
            return None
        try:
            return int((self.backlight / "max_brightness").read_text().strip())
        except Exception:
            return None

    def set_brightness(self, value: int):
        if not self.backlight:
            return False
        try:
            max_b = self.get_max_brightness()
            if max_b is not None:
                value = max(0, min(value, max_b))
            (self.backlight / "brightness").write_text(str(value))
            return True
        except Exception:
            return False

    def set_brightness_percent(self, percent: int):
        max_b = self.get_max_brightness()
        if max_b is None:
            return False
        value = int(max_b * percent / 100)
        return self.set_brightness(value)

    def save_state(self, path: Path | str | None = None):
        if path is None:
            path = DEFAULT_STATE_PATH
            try:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                path = USER_STATE_PATH
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        state = {
            "brightness": self.get_brightness(),
            "max_brightness": self.get_max_brightness(),
            "backlight": str(self.backlight) if self.backlight else None,
        }
        try:
            path.write_text(json.dumps(state))
            return path
        except Exception:
            return None

    def restore_state(self, path: Path | str | None = None):
        if path is None:
            path = DEFAULT_STATE_PATH
            if not Path(path).exists():
                path = USER_STATE_PATH
        path = Path(path)
        if not path.exists():
            return False
        try:
            state = json.loads(path.read_text())
            b = state.get("brightness")
            if b is not None:
                return self.set_brightness(int(b))
        except Exception:
            return False
        return False

