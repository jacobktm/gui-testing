import os

import pytest

from harness.brightness import BrightnessHandler
from handlers.system76_power import System76Power


class TestBrightness:
    def test_brightness_balanced_max(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_up_to_max()
        s.switch_perf_profile("balanced")
        import time; time.sleep(2)
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.balanced_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        # Should drop to ~50% when going to balanced from max
        assert cur is not None
        assert cur <= int(max_b * 0.6) + 2, f"brightness={cur}/{max_b} (expected <= {int(max_b * 0.6) + 2})"

    def test_brightness_battery_max(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_up_to_max()
        s.switch_perf_profile("battery")
        import time; time.sleep(2)
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.battery_max", "verify", f"brightness={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur is not None
        assert cur <= int(max_b * 0.2) + 2, f"brightness={cur}/{max_b} (expected <= {int(max_b * 0.2) + 2})"

    def test_brightness_balanced_min(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_down_to_min()
        before = b.current()
        s.switch_perf_profile("balanced")
        import time; time.sleep(2)
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.balanced_min", "verify", f"before={before} after={cur}/{max_b}\n", step="check")
            except Exception:
                pass
        assert cur == before


    @pytest.mark.reboot
    def test_brightness_preserved_across_reboot(self, artifacts):
        """System restart: screen brightness should be the same as before."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.check_brightness_after_reboot()
        assert res.success, res.summary


    def test_brightness_daemon_restart(self, artifacts):
        """Daemon restart: brightness should not change when daemon defaults to balanced.

Applies to both GNOME and COSMIC desktops.
"""
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        b.brightness_up_to_max()
        before = b.current()
        assert before is not None
        ok = s.restart_daemon()
        if not ok:
            pytest.skip("could not restart daemon (sudo required)")
        # Give daemon a moment to settle
        import time
        time.sleep(2)
        after = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.daemon_restart", "verify", f"before={before} after={after}/{max_b}\n", step="check")
            except Exception:
                pass
        assert after is not None
        assert abs(after - before) <= max(1, max_b // 20)
