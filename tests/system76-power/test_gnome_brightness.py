import os

import pytest

from harness.brightness import BrightnessHandler
from handlers.system76_power import System76Power


@pytest.mark.gnome
class TestGNOMEBrightness:
    def test_brightness_balanced_max(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_up_to_max()
        s.switch_perf_profile("balanced")
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_balanced_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        # Should drop to ~50% when going to balanced from max
        assert cur is not None
        assert cur <= int(max_b * 0.6) + 2  # allow some tolerance

    def test_brightness_battery_max(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_up_to_max()
        s.switch_perf_profile("battery")
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_battery_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur is not None
        assert cur <= int(max_b * 0.2) + 2

    def test_brightness_balanced_min(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_down_to_min()
        before = b.current()
        s.switch_perf_profile("balanced")
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("gnome.brightness_balanced_min", "verify", f"before={before} after={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur == before
