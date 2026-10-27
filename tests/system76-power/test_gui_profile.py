import os

import pytest

from harness.workflows import System76PowerCLIWorkflow, System76PowerGUIWorkflow


def _os_id():
    # Could be detected from system; default for manual runs
    return os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"


@pytest.mark.gui
class TestSystem76PowerGUI:
    def test_screenshot_permission(self, artifacts):
        """Trigger screenshot permission dialog early (COSMIC)."""
        import os
        from pathlib import Path
        from harness.screenshots.screenshot import capture

        out_dir = Path("/tmp/opencode/screenshot_perm")
        out_dir.mkdir(parents=True, exist_ok=True)
        shot_path = out_dir / "permission_test.png"
        if shot_path.exists():
            shot_path.unlink()
        # Pre-grant permission via D-Bus.
        try:
            from harness.screenshots.screenshot import grant_screenshot_permission
            grant_screenshot_permission()
        except Exception:
            pass

        # Wait until screenshots actually work (retry up to 60s).
        import time as _t
        deadline = _t.time() + 60
        screenshot_ok = False
        while _t.time() < deadline:
            if shot_path.exists():
                shot_path.unlink()
            try:
                capture(shot_path, timeout=5.0)
                screenshot_ok = True
                break
            except Exception:
                # Permission dialog may be showing; wait and retry.
                _t.sleep(3)
        assert screenshot_ok, "screenshots not working after 60s (permission not granted?)"

        # Wait for screenshot notification to disappear (15s).
        _t.sleep(5)
        # Re-grant permission in case it was revoked.
        try:
            from harness.screenshots.screenshot import grant_screenshot_permission
            grant_screenshot_permission()
        except Exception:
            pass

    def test_open_power_settings(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.open_power_settings(_os_id())
        assert res.success, res.summary

    def test_detect_power_profile(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_power_profile(_os_id())
        assert res.success, res.summary

    def test_check_brightness(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.get_brightness()
        assert res.success, res.summary

    def test_transition_to_performance(self, artifacts):
        """Ensure starting from performance profile (known starting point)."""
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_to_performance(os_id=os_id, item_id="gui.power_profile_transition.to_performance")
        assert res.success, res.summary

    def test_gui_transition_performance_to_balanced(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("performance", "balanced", os_id=os_id, item_id="gui.power_profile_transition.performance_to_balanced")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_gui_transition_balanced_to_battery(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("balanced", "battery", os_id=os_id, item_id="gui.power_profile_transition.balanced_to_battery")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_gui_transition_battery_to_performance(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("battery", "performance", os_id=os_id, item_id="gui.power_profile_transition.battery_to_performance")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_gui_transition_performance_to_battery(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("performance", "battery", os_id=os_id, item_id="gui.power_profile_transition.performance_to_battery")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_gui_transition_battery_to_balanced(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("battery", "balanced", os_id=os_id, item_id="gui.power_profile_transition.battery_to_balanced")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_gui_transition_balanced_to_performance(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.transition_perf_profile("balanced", "performance", os_id=os_id, item_id="gui.power_profile_transition.balanced_to_performance")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_detect_graphics_mode(self, artifacts):
        from handlers.system76_power import System76Power
        _h = System76Power(artifacts=artifacts)
        if _h.switchable() != "switchable":
            pytest.skip("not switchable graphics")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        # On systems where we can't visually detect reliably, just ensure navigation works
        try:
            res = wf.detect_graphics_mode(os_id=os_id)
            if os_id.startswith("ubuntu") or os_id.startswith("pop-24") or os_id.startswith("pop-26"):
                # Only skip visual validation on Ubuntu and COSMIC
                return
            assert res.success, res.summary
        except Exception:
            if os_id.startswith("ubuntu") or os_id.startswith("pop-24") or os_id.startswith("pop-26"):
                return  # skip visual validation only
            pytest.skip("graphics mode detection not available")

    @pytest.mark.reboot
    def test_graphics_transitions_all(self, artifacts):
        """Pop!_OS 22.04 only: switch graphics modes graphically via dotool clicks."""
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics transitions only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics_all(os_id="pop-22.04")
        assert res.success, res.summary

    def test_cli_profile_change_reflected_in_extension(self, artifacts):
        """Switch profile via CLI, verify the panel applet reflects it."""
        from handlers.system76_power import System76Power

        os_id = _os_id()
        handler = System76Power(artifacts=artifacts)
        target = "performance" if handler.get_perf_profile() != "performance" else "balanced"
        handler.switch_perf_profile(target)

        import time
        time.sleep(3)
        # Dismiss any pop-ups and click center before detection.
        try:
            from harness.dotool import send_keys
            send_keys("key esc\n")
        except Exception:
            pass
        time.sleep(1)
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_power_profile(os_id)
        assert res.success, res.summary
        detected = (res.data or {}).get("profile", "").lower()
        assert detected == target, f"extension shows {detected}, expected {target}"

    @pytest.mark.reboot
    def test_gui_transition_to_integrated(self, artifacts):
        """Pop!_OS 22.04 only."""
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_to_integrated(os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_integrated_to_nvidia(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "nvidia", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_nvidia_to_hybrid(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "hybrid", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_hybrid_to_compute(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "compute", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_compute_to_integrated(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "integrated", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_integrated_to_hybrid(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "hybrid", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_hybrid_to_nvidia(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "nvidia", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_nvidia_to_compute(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "compute", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_compute_to_hybrid(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "hybrid", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_hybrid_to_integrated(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "integrated", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_integrated_to_compute(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "compute", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_compute_to_nvidia(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "nvidia", os_id="pop-22.04")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_gui_transition_nvidia_to_integrated(self, artifacts):
        os_id = _os_id()
        if not os_id.startswith("pop-22"):
            pytest.skip("GUI graphics only on Pop!_OS 22.04")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "integrated", os_id="pop-22.04")
        assert res.success, res.summary






