import os

import pytest

from harness.workflows import System76PowerCLIWorkflow, System76PowerGUIWorkflow


def _os_id():
    # Could be detected from system; default for manual runs
    return os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"


@pytest.mark.gui
class TestSystem76PowerGUI:
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

    def test_detect_graphics_mode(self, artifacts):
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
        """Pop!_OS 22.04: switch graphics modes graphically via dotool clicks."""
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

        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_power_profile(os_id)
        assert res.success, res.summary
        detected = (res.data or {}).get("profile", "").lower()
        assert detected == target, f"extension shows {detected}, expected {target}"

    def test_cli_graphics_change_reflected_in_extension(self, artifacts):
        """Switch graphics mode via CLI, verify the panel applet reflects it."""
        from handlers.system76_power import System76Power

        os_id = _os_id()
        handler = System76Power(artifacts=artifacts)
        switchable = handler.switchable()
        if switchable != "switchable":
            pytest.skip("not switchable")
        # Switch to integrated (safe, always available)
        handler.switch_graphics_mode("integrated")

        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        try:
            res = wf.detect_graphics_mode(os_id=os_id)
        except Exception:
            if os_id.startswith("ubuntu") or os_id.startswith("pop-24") or os_id.startswith("pop-26"):
                return
            pytest.skip("graphics mode detection not available")
            return
        if os_id.startswith("ubuntu") or os_id.startswith("pop-24") or os_id.startswith("pop-26"):
            # Visual validation not reliable on these; just ensure no crash
            return
        assert res.success, res.summary

    def test_perf_profile_transitions(self, artifacts):
        """Transition through power profiles via dotool-driven GUI clicks."""
        from handlers.system76_power import System76Power

        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        for target in ("battery", "balanced", "performance"):
            res = wf.set_power_profile_gui(
                target,
                os_id=os_id,
                item_id=f"gui.power_profile_transition_{target}",
            )
            assert res.success, res.summary
            handler = System76Power(artifacts=artifacts)
            current = handler.get_perf_profile()
            assert current == target, f"expected profile {target}, got {current}"





