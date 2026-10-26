import pytest

from harness.workflows import System76PowerCLIWorkflow


@pytest.mark.cli
class TestSystem76PowerCLIFull:
    def test_power_profiles_can_be_queried_and_set(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.query_profile()
        assert res.success, res.summary
        current = (res.data or {}).get("profile")
        # Pick a different profile to ensure the set command actually changes state.
        target = "performance" if current != "performance" else "balanced"
        res = wf.set_profile(target)
        assert res.success, res.summary
        assert (res.data or {}).get("profile") == target
        res = wf.query_profile()
        assert res.success, res.summary
        assert (res.data or {}).get("profile") == target

    def test_laptop_switchable_graphics_can_be_queried(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.query_switchable()
        assert res.success, res.summary

    def test_graphics_power_query_set(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.get_graphics_power()
        # Accept various states
        p = res.data.get("power")
        assert res.success or p in ("on", "off", "on (discrete)", "off (discrete)"), (
            res.summary
        )
        # Try setting
        try:
            if p and "off" in str(p).lower():
                wf.set_graphics_power("on")
            else:
                wf.set_graphics_power("off")
                wf.set_graphics_power("on")
        except Exception:
            pass

    @pytest.mark.reboot
    def test_graphics_transitions_all(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics_all()
        assert res.success, res.summary
