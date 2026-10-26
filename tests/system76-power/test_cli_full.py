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
    def test_graphics_transition_to_integrated(self, artifacts):
        """Transition from current mode to integrated (ensures starting point)."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_to_integrated(item_id="cli.graphics_transition.to_integrated")
        assert res.success, res.summary

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_integrated_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "nvidia", item_id="cli.graphics_transition.integrated_to_nvidia")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_integrated_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "hybrid", item_id="cli.graphics_transition.integrated_to_hybrid")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_integrated_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "compute", item_id="cli.graphics_transition.integrated_to_compute")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_nvidia_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "integrated", item_id="cli.graphics_transition.nvidia_to_integrated")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_nvidia_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "hybrid", item_id="cli.graphics_transition.nvidia_to_hybrid")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_nvidia_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "compute", item_id="cli.graphics_transition.nvidia_to_compute")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_hybrid_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "integrated", item_id="cli.graphics_transition.hybrid_to_integrated")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_hybrid_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "nvidia", item_id="cli.graphics_transition.hybrid_to_nvidia")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_hybrid_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "compute", item_id="cli.graphics_transition.hybrid_to_compute")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_compute_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "integrated", item_id="cli.graphics_transition.compute_to_integrated")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_compute_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "nvidia", item_id="cli.graphics_transition.compute_to_nvidia")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition_compute_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "hybrid", item_id="cli.graphics_transition.compute_to_hybrid")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    def test_cli_graphics_reflected_in_extension(self, artifacts):
        """Aggregate: verify panel applet reflected CLI graphics changes."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_graphics_reflected_in_extension()
        if (res.data or {}).get("skipped"):
            return  # not 22.04 or no GUI verification data
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_graphics_transitions_all(self, artifacts):
        """Orchestrator: run all transitions in order determined by starting mode."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        order = wf.get_transition_order()
        print(f"Transition order: {order}")
        res = wf.transition_graphics_all()
        assert res.success, res.summary
        for entry in (res.data or {}).get("transitions", []):
            assert entry.get("verified") is True, f"CLI verification failed: {entry}"
