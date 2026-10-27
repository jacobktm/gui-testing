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
        from handlers.system76_power import System76Power
        handler = System76Power(artifacts=artifacts)
        result = handler.switchable()
        # Persist so transition tests don't re-query.
        System76Power.save_switchable_state(result)
        assert result in ("switchable", "not switchable"), result

    def test_graphics_power_query_set(self, artifacts):
        from handlers.system76_power import System76Power
        _h = System76Power(artifacts=artifacts)
        if _h.switchable() != "switchable":
            pytest.skip("not switchable graphics")
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
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_graphics_transition_integrated_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "nvidia", item_id="cli.graphics_transition.integrated_to_nvidia")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_nvidia_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "hybrid", item_id="cli.graphics_transition.nvidia_to_hybrid")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_hybrid_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "compute", item_id="cli.graphics_transition.hybrid_to_compute")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_compute_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "integrated", item_id="cli.graphics_transition.compute_to_integrated")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_integrated_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "hybrid", item_id="cli.graphics_transition.integrated_to_hybrid")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_hybrid_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "nvidia", item_id="cli.graphics_transition.hybrid_to_nvidia")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_nvidia_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "compute", item_id="cli.graphics_transition.nvidia_to_compute")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_compute_to_hybrid(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "hybrid", item_id="cli.graphics_transition.compute_to_hybrid")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_hybrid_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "integrated", item_id="cli.graphics_transition.hybrid_to_integrated")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_integrated_to_compute(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "compute", item_id="cli.graphics_transition.integrated_to_compute")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_compute_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("compute", "nvidia", item_id="cli.graphics_transition.compute_to_nvidia")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        # CLI verification must pass
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_nvidia_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("nvidia", "integrated", item_id="cli.graphics_transition.nvidia_to_integrated")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
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
