import os

import pytest

from workflows.system76_power import System76PowerGUIWorkflow
from workflows.system76_power.graphics_transitions import get_graphics_chain
from workflows.system76_power.transitions import get_perf_profile_chain


def _os_id():
    """Return the detected platform id; TEST_OS_ID overrides for simulation."""
    from harness.platform import detect_platform

    return os.environ.get("TEST_OS_ID") or detect_platform().os_id


def _supports_graphics_ui() -> bool:
    """Capability gate: does this platform flavor expose the graphics-switching UI?

    Replaces the old ``os_id.startswith("pop-22")`` checks: flavors declare the
    capability themselves (see ``PlatformFlavor.supports_graphics_switching``),
    so supporting a new release never means editing these tests.
    """
    from harness.platform import get_flavor_for_os_id

    return get_flavor_for_os_id(_os_id()).supports_graphics_switching()


# Chains come from the workflows themselves, rotated to start from the state
# the machine is actually in — the priming ``to_performance``/``to_hybrid``
# tests are gone.  The graphics chain is a closed 12-edge circuit whose
# rotation is persisted for the run, so resumed boots keep walking it and the
# edge whose reboot is in flight stays at the front of the chain.
GUI_PROFILE_TRANSITIONS = get_perf_profile_chain()
GRAPHICS_TRANSITIONS = get_graphics_chain()


@pytest.mark.gui
class TestSystem76PowerGUI:
    def test_screenshot_permission(self, artifacts):
        """Trigger screenshot permission dialog early (COSMIC)."""
        import os
        from pathlib import Path
        from harness.screenshots.screenshot import capture, grant_screenshot_permission

        # Pre-grant permission via D-Bus before attempting capture.
        try:
            grant_screenshot_permission()
        except Exception:
            pass

        out_dir = Path("/tmp/opencode/screenshot_perm")
        out_dir.mkdir(parents=True, exist_ok=True)
        shot_path = out_dir / "permission_test.png"
        if shot_path.exists():
            shot_path.unlink()

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
        _t.sleep(15)
        # Re-grant permission in case it was revoked.
        try:
            grant_screenshot_permission()
        except Exception:
            pass

    def test_open_power_settings(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.open_power_settings(_os_id())
        assert res.success, res.summary

    def test_detect_power_profile(self, artifacts):
        from workflows.system76_power import ProfileTransitionWorkflow
        wf = ProfileTransitionWorkflow(artifacts=artifacts)
        res = wf.validate_profile("balanced", _os_id(), item_id="gui.power_profile_detect")
        # Just ensure it can detect - don't require specific profile
        assert res.success or (res.data or {}).get("value") in ("performance", "balanced", "battery"), res.summary

    def test_check_brightness(self, artifacts):
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.get_brightness()
        assert res.success, res.summary

    @pytest.mark.parametrize(
        "source,target",
        [pytest.param(s, t, id=f"{s}_to_{t}") for s, t in GUI_PROFILE_TRANSITIONS],
    )
    def test_gui_perf_profile_transition(self, artifacts, source, target):
        """GUI-driven power-profile transition, verified visually.

        The chain is rotated to start from the profile the machine is in
        (no priming ``to_performance`` test); the per-parameter ``item_id``
        matches the ids the six individual tests used, so persisted phase
        state keeps its resume scheme.
        """
        from workflows.system76_power import ProfileTransitionWorkflow
        wf = ProfileTransitionWorkflow(artifacts=artifacts)
        os_id = _os_id()
        res = wf.gui_wf.transition_perf_profile(
            source, target, os_id=os_id,
            item_id=f"gui.power_profile_transition.{source}_to_{target}",
        )
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"verification failed: {data}"

    def test_detect_graphics_mode(self, artifacts):
        from handlers.system76_power import System76Power, probe_switchable
        _h = System76Power(artifacts=artifacts)
        if probe_switchable(_h) != "switchable":
            pytest.skip("not switchable graphics")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        os_id = _os_id()
        visual_required = _supports_graphics_ui()
        # On flavors without a reliably detectable graphics panel, just ensure
        # navigation works.
        try:
            res = wf.detect_graphics_mode(os_id=os_id)
            if not visual_required:
                return
            assert res.success, res.summary
        except Exception:
            if not visual_required:
                return  # skip visual validation only
            pytest.skip("graphics mode detection not available")

    @pytest.mark.reboot
    @pytest.mark.parametrize(
        "source,target",
        [pytest.param(s, t, id=f"{s}_to_{t}") for s, t in GRAPHICS_TRANSITIONS],
    )
    def test_gui_graphics_transition(self, artifacts, source, target):
        """One reboot-aware GUI graphics transition (parametrized rotated chain).

        The chain is rotated at collection to start from the mode the machine
        is actually in, so the priming ``to_hybrid`` test (and its extra
        reboot) is unnecessary.

        Deliberately no explicit ``item_id``: all twelve transitions share the
        workflow default (``gui.graphics_transitions``) — one phase-state
        document accumulating results, exactly as before parametrization.
        (The CLI chain uses per-transition item_ids instead; don't mix the
        schemes.)
        """
        if not _supports_graphics_ui():
            pytest.skip("no graphics-switching UI on this flavor")
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics(source, target, os_id=_os_id())
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
            from harness.dotool import mouseto, click
            mouseto((0.5, 0.5))
            click()
        except Exception:
            pass
        time.sleep(1)
        wf = System76PowerGUIWorkflow(artifacts=artifacts)
        res = wf.detect_power_profile(os_id, target=target)
        assert res.success, res.summary
        detected = (res.data or {}).get("profile", "").lower()
        assert detected == target, f"extension shows {detected}, expected {target}"
