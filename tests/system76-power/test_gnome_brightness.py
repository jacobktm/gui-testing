import os

import pytest

from handlers.brightness import Brightness
from handlers.system76_power import System76Power


@pytest.mark.gnome
class TestGNOMEBrightness:
    def test_brightness_balanced_max(self, artifacts):
        b = Brightness()
        s = System76Power(artifacts=artifacts)
        max_b = b.get_max_brightness()
        if max_b is None:
            pytest.skip("no backlight")
        b.set_brightness(max_b)
        s.switch_perf_profile("balanced")
        cur = b.get_brightness()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_balanced_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        # Should drop to ~50% when going to balanced from max
        assert cur is not None
        assert cur <= int(max_b * 0.6) + 2  # allow some tolerance

    def test_brightness_battery_max(self, artifacts):
        b = Brightness()
        s = System76Power(artifacts=artifacts)
        max_b = b.get_max_brightness()
        if max_b is None:
            pytest.skip("no backlight")
        b.set_brightness(max_b)
        s.switch_perf_profile("battery")
        cur = b.get_brightness()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_battery_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur is not None
        assert cur <= int(max_b * 0.2) + 2

    def test_brightness_balanced_min(self, artifacts):
        b = Brightness()
        s = System76Power(artifacts=artifacts)
        max_b = b.get_max_brightness()
        if max_b is None:
            pytest.skip("no backlight")
        b.set_brightness(0)
        before = b.get_brightness()
        s.switch_perf_profile("balanced")
        cur = b.get_brightness()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_balanced_min", "verify", f"before={before} after={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur == before
