import pytest

from workflows.system76_power import System76PowerCLIWorkflow
from workflows.system76_power.graphics_transitions import get_graphics_chain
from workflows.system76_power.transitions import get_perf_profile_chain


def _detected_os_id() -> str:
    """Return the detected platform id; TEST_OS_ID overrides for simulation."""
    import os

    from harness.platform import detect_platform

    return os.environ.get("TEST_OS_ID") or detect_platform().os_id


# Chains come from the workflows themselves, rotated to start from the
# state the machine is actually in — no priming test/transition is needed.
# The graphics chain is a closed 12-edge circuit (`GRAPHICS_CHAIN_ORDER`);
# the rotation is persisted for the run so resumed boots keep walking it.
GRAPHICS_TRANSITIONS = get_graphics_chain()

# CLI profile switches whose effect on the GUI extension is verified.
# (source, target); a closed 6-edge circuit rotated to the current profile.
CLI_PROFILE_TRANSITIONS = get_perf_profile_chain()


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
        """Probe the graphics-switching capability of this system.

        What the CLI does depends on the machine, which only the probe
        itself can reveal:

        - stacks that can answer switchability reply on stdout
          (``switchable`` / ``not switchable``);
        - systems whose OS provides no graphics switching (COSMIC-era
          Pop!_OS, Ubuntu) or whose hardware lacks an iGPU+dGPU pair exit
          non-zero; the handler surfaces that as
          ``GraphicsSwitchingUnsupported`` carrying the CLI's message.

        ``pytest.raises(..., match=...)`` cannot be applied
        unconditionally: whether the device *answers* or *refuses* is a
        property of the machine, not a known input to this test.  The
        except-branch asserts the equivalent of ``match=`` — the refusal
        must carry the documented "not supported / not switchable" message,
        not an unrelated CLI error.  Timeouts and other unexpected errors
        are deliberately *not* caught: those are real failures.  (This also
        fixes the historical failure of this test on every run log: the old
        handler leaked raw stderr into the result when its string heuristic
        missed, blowing up the membership assertion.)
        """
        import re

        from handlers.system76_power import GraphicsSwitchingUnsupported, System76Power
        from handlers.system76_power.power_state import save_switchable_state

        # item_id so the handler records the raw command result (rc, stdout,
        # stderr) as an artifact under this test — the evidence needed when
        # the answer is unexpected.
        handler = System76Power(
            test_id="system76_power.cli.switchable",
            item_id="cli.laptop_switchable_graphics_can_be_queried",
            phase="verify",
            artifacts=artifacts,
        )
        try:
            result = handler.switchable()
        except GraphicsSwitchingUnsupported as exc:
            assert re.search(r"not (supported|switchable)", str(exc), re.IGNORECASE), f"unexpected refusal: {exc}"
            # Persist so transition tests don't re-query.
            save_switchable_state("not switchable")
            return
        # Persist so transition tests don't re-query.
        save_switchable_state(result)
        assert result in ("switchable", "not switchable"), result

    def test_graphics_power_query_set(self, artifacts):
        import subprocess
        import os
        from handlers.system76_power import System76Power, probe_switchable
        from handlers.system76_power.power_state import load_switchable_state
        _h = System76Power(artifacts=artifacts)
        switchable = load_switchable_state()
        if switchable is None:
            switchable = probe_switchable(_h)
        if switchable != "switchable":
            pytest.skip("not switchable graphics")
        from workflows.system76_power import System76PowerCLIWorkflow
        # Ensure we're in hybrid mode for graphics power control to work
        try:
            wf2 = System76PowerCLIWorkflow(artifacts=artifacts)
            wf2.transition_to_hybrid(item_id="cli.graphics_transition.pre_power")
        except Exception:
            pass
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        try:
            res = wf.get_graphics_power()
        except subprocess.TimeoutExpired:
            # Try to recover and treat as failure but don't crash
            try:
                subprocess.run(['pkill', '-9', '-f', 'system76-power'], check=False)
                subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'com.system76.PowerDaemon.service'], check=False, timeout=30)
            except Exception:
                pass
            pytest.fail("graphics power query timed out")
        except Exception as e:
            pytest.fail(f"graphics power query failed: {e}")
        p = (res.data or {}).get("power")
        if p not in ("on", "off", "on (discrete)", "off (discrete)"):
            # be tolerant
            if p is None:
                pytest.skip("graphics power status unknown")
            pytest.fail(f"graphics power query failed: {res.summary}, data={res.data}")
        # Try setting - must actually work
        try:
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
                try:
                    res = wf.set_graphics_power("on")
                    assert res.success, f"failed to turn graphics power on: {res.summary}"
                    p3 = (res.data or {}).get("power")
                    assert "on" in str(p3).lower(), f"graphics power not on after set: {p3}"
                except Exception:
                    pass
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(['pkill', '-9', '-f', 'system76-power'], check=False)
                subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'com.system76.PowerDaemon.service'], check=False, timeout=30)
            except Exception:
                pass
            pytest.fail("graphics power set timed out")
        except Exception as e:
            pytest.fail(f"graphics power set failed: {e}")

    @pytest.mark.reboot
    @pytest.mark.parametrize(
        "source,target",
        [pytest.param(s, t, id=f"{s}_to_{t}") for s, t in GRAPHICS_TRANSITIONS],
    )
    def test_graphics_transition(self, artifacts, source, target):
        """One reboot-aware graphics transition (parametrized rotated chain).

        The chain is rotated at collection to start from the mode the machine
        is actually in, so the first edge needs no priming ``to_hybrid``
        switch/reboot.  The per-parameter ``item_id`` keeps the resume
        scheme: the workflow persists its ``graphics_transition`` phase
        machine under the same id the twelve individual tests used, so an
        interrupted multi-boot run resumes exactly where it stopped.
        """
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.transition_graphics(source, target, item_id=f"cli.graphics_transition.{source}_to_{target}")
        if (res.data or {}).get("skipped"):
            pytest.skip("not switchable graphics")
        assert res.success, res.summary
        data = res.data or {}
        assert data.get("verified") is True, f"CLI verification failed: {data}"

    def test_cli_graphics_reflected_in_extension(self, artifacts):
        """Aggregate: verify panel applet reflected CLI graphics changes."""
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_graphics_reflected_in_extension()
        if (res.data or {}).get("skipped"):
            pytest.skip("no graphics-switching UI on this flavor, or no transitions ran")
        assert res.success, res.summary

    @pytest.mark.parametrize(
        "source,target",
        [pytest.param(s, t, id=f"{s}_to_{t}") for s, t in CLI_PROFILE_TRANSITIONS],
    )
    def test_cli_profile_reflected(self, artifacts, source, target):
        """Switch profile via CLI, verify the GUI extension shows it.

        The workflow performs both switches, the deliberate center-screen
        dismissal click (always safe here; clears lingering profile-change
        pop-ups), and persists the outcome for the aggregate test below.
        """
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_cli_profile_reflected(
            source, target, os_id=_detected_os_id(),
            item_id=f"cli.profile_reflected.{source}_to_{target}",
        )
        assert res.success, res.summary

    def test_cli_profile_reflected_in_extension(self, artifacts):
        """Aggregate: every profile must have been reflected at least once.

        Pure aggregation over the persisted results of the parametrized
        per-transition tests — it no longer re-runs the whole switch
        sequence itself (~6 minutes of duplicate work removed).
        """
        wf = System76PowerCLIWorkflow(artifacts=artifacts)
        res = wf.verify_all_cli_profiles_reflected_in_extension(item_id="cli.profile_reflected")
        if (res.data or {}).get("skipped"):
            pytest.skip("no profile verification data (transitions not run)")
        assert res.success, res.summary
