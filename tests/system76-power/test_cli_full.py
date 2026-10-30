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
        from harness.workflows.system76_power.state import save_switchable_state
        handler = System76Power(artifacts=artifacts)
        result = handler.switchable()
        # Persist so transition tests don't re-query.
        save_switchable_state(result)
        assert result in ("switchable", "not switchable"), result

    def test_graphics_power_query_set(self, artifacts):
        from handlers.system76_power import System76Power
        _h = System76Power(artifacts=artifacts)
        if _h.switchable() != "switchable":
            pytest.skip("not switchable graphics")
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.get_graphics_power()
        p = (res.data or {}).get("power")
        assert p in ("on", "off", "on (discrete)", "off (discrete)"), f"graphics power query failed: {res.summary}, data={res.data}"
        # Try setting - must actually work
        if "off" in str(p).lower():
            res = wf.set_graphics_power("on")
            assert res.success, f"failed to turn graphics power on: {res.summary}"
            p2 = (res.data or {}).get("power")
            assert "on" in str(p2).lower(), f"graphics power not on after set: {p2}"
        else:
            res = wf.set_graphics_power("off")
            assert res.success, f"failed to turn graphics power off: {res.summary}"
            p2 = (res.data or {}).get("power")
            assert "off" in str(p2).lower(), f"graphics power not off after set: {p2}"
            res = wf.set_graphics_power("on")
            assert res.success, f"failed to turn graphics power on: {res.summary}"
            p3 = (res.data or {}).get("power")
            assert "on" in str(p3).lower(), f"graphics power not on after set: {p3}"

    @pytest.mark.reboot
    def test_graphics_transition_to_hybrid(self, artifacts):
        """Transition from current mode to hybrid (ensures starting point)."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_to_hybrid(item_id="cli.graphics_transition.to_hybrid")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary

    @pytest.mark.reboot
    def test_graphics_transition_hybrid_to_integrated(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("hybrid", "integrated", item_id="cli.graphics_transition.hybrid_to_integrated")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    @pytest.mark.reboot
    def test_graphics_transition_integrated_to_nvidia(self, artifacts):
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics("integrated", "nvidia", item_id="cli.graphics_transition.integrated_to_nvidia")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
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
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    def test_cli_graphics_reflected_in_extension(self, artifacts):
        """Aggregate: verify panel applet reflected CLI graphics changes."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_graphics_reflected_in_extension()
        if (res.data or {}).get("skipped"):
            return  # not 22.04 or no GUI verification data
        assert res.success, res.summary

    def test_transition_to_performance(self, artifacts):
        """Ensure starting from performance profile (known starting point)."""
        from handlers.system76_power import System76Power
        handler = System76Power(artifacts=artifacts)
        current = handler.get_perf_profile()
        if current == "performance":
            return
        handler.switch_perf_profile("performance")
        import time
        time.sleep(1)
        assert handler.get_perf_profile() == "performance"

    def test_cli_profile_performance_to_balanced(self, artifacts):
        """Switch to balanced via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("balanced", os_id=os_id, item_id="cli.profile_reflected.performance_to_balanced")
        assert res.success, res.summary

    def test_cli_profile_balanced_to_battery(self, artifacts):
        """Switch to battery via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("battery", os_id=os_id, item_id="cli.profile_reflected.balanced_to_battery")
        assert res.success, res.summary

    def test_cli_profile_battery_to_performance(self, artifacts):
        """Switch to performance via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("performance", os_id=os_id, item_id="cli.profile_reflected.battery_to_performance")
        assert res.success, res.summary

    def test_cli_profile_performance_to_battery(self, artifacts):
        """Switch to battery via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("battery", os_id=os_id, item_id="cli.profile_reflected.performance_to_battery")
        assert res.success, res.summary

    def test_cli_profile_battery_to_balanced(self, artifacts):
        """Switch to balanced via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("balanced", os_id=os_id, item_id="cli.profile_reflected.battery_to_balanced")
        assert res.success, res.summary

    def test_cli_profile_balanced_to_performance(self, artifacts):
        """Switch to performance via CLI, verify GUI reflects it."""
        from harness.workflows import System76PowerCLIWorkflow
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected_in_extension("performance", os_id=os_id, item_id="cli.profile_reflected.balanced_to_performance")
        assert res.success, res.summary

    def test_cli_profile_reflected_in_extension(self, artifacts):
        """Test that any power profile change from CLI is reflected in the extension."""
        from harness.workflows import System76PowerCLIWorkflow

        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_all_cli_profiles_reflected_in_extension(item_id="cli.profile_reflected")
        if (res.data or {}).get("skipped"):
            return
        assert res.success, res.summary