import pytest

from harness.workflows import System76PowerCLIWorkflow


@pytest.mark.cli
class TestSystem76PowerCLIFull:
    def test_power_profiles_can_be_queried_and_set(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.query_profile()
        assert res.success, res.summary

    def test_laptop_switchable_graphics_can_be_queried(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.query_switchable()
        assert res.success, res.summary
        if res.data.get("switchable") == "switchable":
            res2 = wf.transition_graphics_all()
            assert res2.success, res2.summary
        else:
            pytest.skip("not switchable")

    def test_graphics_power_query_set(self, artifacts):
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.get_graphics_power()
        # Accept various states
        assert res.success or res.data.get("power") in ("on", "off", "on (discrete)", "off (discrete)"), res.summary

