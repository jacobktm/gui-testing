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
        # Start from performance so the switch to balanced triggers the drop.
        s.switch_perf_profile("performance")
        import time; time.sleep(1)
        b.brightness_up_to_max()
        s.switch_perf_profile("balanced")
        time.sleep(2)
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.balanced_max", "verify", f"brightness={cur}/{max_b} ({(cur/max_b*100):.0f}%)\n", step="check")
            except Exception:
                pass
        # Should drop to ~50% when going to balanced from max.
        # Percentage matters more than raw value (max varies by system).
        pct = (cur / max_b * 100) if max_b else 0
        assert cur is not None, f"brightness={cur}/{max_b}"
        assert pct <= 60, f"brightness={cur}/{max_b} ({pct:.0f}%, expected <= 60%)" 

    def test_brightness_battery_max(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        # Start from performance so the switch to battery triggers the drop.
        s.switch_perf_profile("performance")
        import time; time.sleep(1)
        b.brightness_up_to_max()
        s.switch_perf_profile("battery")
        time.sleep(2)
        cur = b.current()
        if artifacts:
            try:
                artifacts.save_text("brightness.battery_max", "verify", f"brightness={cur}/{max_b} ({(cur/max_b*100):.0f}%)\n", step="check")
            except Exception:
                pass
        pct = (cur / max_b * 100) if max_b else 0
        assert cur is not None, f"brightness={cur}/{max_b}"
        assert pct <= 20, f"brightness={cur}/{max_b} ({pct:.0f}%, expected <= 20%)" 

    def test_brightness_balanced_min(self, artifacts):
        b = BrightnessHandler()
        s = System76Power(artifacts=artifacts)
        max_b = b.maximum()
        if max_b is None:
            pytest.skip("no backlight")
        # Start from performance so switching to balanced is a real transition.
        s.switch_perf_profile("performance")
        import time; time.sleep(1)
        b.brightness_down_to_min()
        before = b.current()
        s.switch_perf_profile("balanced")
        time.sleep(2)
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
        import subprocess
        # Debug: show system76-power profile output
        r = subprocess.run(["system76-power", "profile"], capture_output=True, text=True, timeout=10)
        print(f"DEBUG profile rc={r.returncode}", flush=True)
        for line in r.stdout.splitlines():
            print(f"DEBUG   {line}", flush=True)
        print(f"DEBUG stderr={r.stderr.strip()}", flush=True)

        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.check_brightness_after_reboot()
        print(f"DEBUG result: success={res.success} summary={res.summary}", flush=True)
        if not res.success:
            pytest.fail(res.summary)


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
            import subprocess
            r = subprocess.run(["sudo", "-n", "systemctl", "restart", "com.system76.PowerDaemon.service"], capture_output=True, text=True, timeout=10)
            print(f"DEBUG restart rc={r.returncode} stderr={r.stderr.strip()}", flush=True)
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
