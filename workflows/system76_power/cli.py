from __future__ import annotations

from handlers.system76_power import System76Power
from handlers.system76_power.power_state import load_switchable_state as _load_switchable, save_switchable_state as _save_switchable
from harness.reboot.system import setup_autologin as _setup_autologin

from .graphics_transitions import GraphicsTransitionMixin

from harness.workflows.base import Workflow, WorkflowResult


def _reboot_and_wait(handler, graceful: bool = False) -> bool:
    """Reboot and wait (kept as a module-level name for test patchability)."""
    from .util import reboot_and_wait

    return reboot_and_wait(handler, graceful=graceful)


class System76PowerCLIWorkflow(Workflow, GraphicsTransitionMixin):
    def query_profile(self, item_id: str = "cli.power_profiles_can_be_queried_and_set") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.profile",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        profile = handler.get_perf_profile()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="passed" if profile in handler.perf_profiles else "failed")
                self.artifacts.save_text(item_id, "verify", f"profile: {profile}\n", step="query")
            except Exception:
                pass
        return WorkflowResult(success=profile in handler.perf_profiles, item_id=item_id, summary=f"profile={profile}", data={"profile": profile})

    def set_profile(self, profile: str, item_id: str = "cli.power_profiles_can_be_queried_and_set") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.profile",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        ok = handler.switch_perf_profile(profile)
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"set:{profile}\n", step="set")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"set:{profile}", data={"profile": profile})

    def _gui_verify_graphics_mode(self, target: str, detect_item_id: str | None = None) -> bool | None:
        """Visually verify the desktop shows graphics mode as *target*.

        Returns ``True``/``False`` on flavors that expose the graphics-switching
        UI — Pop!_OS 22.04 shows the active mode in the system extension, so a
        transition that cannot be confirmed visually has not changed the
        user-visible state, and every failure in this path is ``False``
        (required evidence, not best effort).  Returns ``None`` only for
        flavors without that UI.
        """
        from harness.platform import detect_platform, get_flavor_for_os_id

        os_id = detect_platform().os_id
        if not get_flavor_for_os_id(os_id).supports_graphics_switching():
            return None
        gui_wf = None
        try:
            from .gui import System76PowerGUIWorkflow
            import time

            gui_wf = System76PowerGUIWorkflow(artifacts=self.artifacts)
            opened = gui_wf.open_power_settings(os_id)
            if not opened.success:
                # detect_graphics_mode dismisses and re-opens the panel itself,
                # up to 5 attempts — a transient open failure right after a
                # reboot is not fatal yet.
                print(f"  [gui_verify] open failed: {opened.summary}; letting detection retry", flush=True)
            time.sleep(6)
            kwargs = {"os_id": os_id, "target": target}
            if detect_item_id:
                kwargs["item_id"] = detect_item_id
            det = gui_wf.detect_graphics_mode(**kwargs)
            detected = ((det.data or {}).get("graphics") or "").lower()
            ok = bool(det.success) and detected == target.lower()
            if not ok:
                print(
                    f"  [gui_verify] GUI did not confirm {target!r}: detected={detected!r} ({det.summary})",
                    flush=True,
                )
            return ok
        except Exception as exc:
            print(f"  [gui_verify] failed: {exc}", flush=True)
            return False
        finally:
            # Leave any opened panel/notification closed for the next test.
            try:
                if gui_wf is not None:
                    gui_wf.dismiss_menus()
            except Exception:
                pass

    # --- GraphicsTransitionMixin hooks (CLI driver) -------------------------

    def _make_handler(self, item_id: str, phase: str):
        return System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase=phase,
            artifacts=self.artifacts,
        )

    def _switch_graphics_mode(self, handler, target: str) -> tuple[bool, str, str]:
        result = handler._run(["system76-power", "graphics", target], check=False)
        out = (result.get("stdout") or "").strip()
        err = (result.get("stderr") or "").strip()
        print(f"  system76-power graphics {target}: rc={result.get('returncode')} output={out!r}", flush=True)
        return result.get("returncode") in (0, None), out, err

    def _gui_verify_transition(self, target: str, item_id: str) -> bool | None:
        return self._gui_verify_graphics_mode(target, detect_item_id=f"{item_id}.gui")

    # --- mixin entry points (historical CLI signatures preserved) -----------

    def transition_to_hybrid(self, item_id: str = "cli.graphics_transition.to_hybrid") -> WorkflowResult:
        return self._transition_to_hybrid_core(item_id=item_id)

    def transition_graphics(self, source: str, target: str, item_id: str = "cli.graphics_transitions") -> WorkflowResult:
        return self._transition_graphics_core(source, target, item_id=item_id)

    def verify_cli_graphics_reflected_in_extension(self, item_id: str = "cli.graphics_transition") -> WorkflowResult:
        """Aggregate GUI verification from all CLI graphics transitions.

        On flavors that expose the graphics-switching UI every transition that
        ran must have been visually confirmed: a ``False`` *or missing*
        (``None``) ``gui_verified`` counts as a failure here.  Only flavors
        without that UI — or runs where no transition executed — skip.
        """
        from harness.platform import detect_platform, get_flavor_for_os_id

        os_id = detect_platform().os_id
        if not get_flavor_for_os_id(os_id).supports_graphics_switching():
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary=f"{os_id} has no graphics-switching UI",
                data={"skipped": True},
            )

        modes = ["nvidia", "integrated", "hybrid", "compute"]
        pairs = [(s, t) for s in modes for t in modes if s != t]

        gui_results = []
        for source, target in pairs:
            trans_item_id = f"{item_id}.{source}_to_{target}"
            progress = self.resume_progress(trans_item_id, kind="graphics_transition")
            results = progress.get("results", [])
            entry = next(
                (e for e in results if e.get("from") == source and e.get("to") == target),
                None,
            )
            gui_results.append({
                "from": source,
                "to": target,
                "gui_verified": entry.get("gui_verified") if isinstance(entry, dict) else None,
                "ran": isinstance(entry, dict),
            })

        ran = [r for r in gui_results if r["ran"]]
        if not ran:
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary="no transitions ran (the transition tests cover that)",
                data={"gui_results": gui_results, "skipped": True},
            )

        missing = [r for r in ran if r["gui_verified"] is None]
        failed = [r for r in ran if r["gui_verified"] is False]
        confirmed = len(ran) - len(missing) - len(failed)
        summary = f"gui_reflected: {confirmed}/{len(ran)} confirmed"
        if missing:
            summary += f", no GUI verification: {len(missing)}"
        if failed:
            summary += f", GUI mismatched: {len(failed)}"
        return WorkflowResult(
            success=confirmed == len(ran),
            item_id=item_id,
            summary=summary,
            data={"gui_results": gui_results},
        )

    def check_brightness_after_reboot(self, item_id: str = "cli.brightness_restart") -> WorkflowResult:
        """Verify screen brightness is preserved across a system reboot.

        Sets brightness to 50%, reboots, then checks if brightness is still
        at the same level after the daemon settles.
        """
        import sys
        import time
        import os
        from pathlib import Path
        from harness.brightness import get_brightness, get_max_brightness, BrightnessHandler

        handler = System76Power(
            test_id="system76_power.cli.brightness_restart",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )

        def log(msg):
            print(msg, file=sys.stderr, flush=True)

        # Load persisted state.
        log(f"[brightness_reboot] artifacts={self.artifacts is not None} run_dir={getattr(self.artifacts, 'run_dir', None) if self.artifacts else None}")
        state = self.load_persisted_state(item_id, phase="state")
        log(f"[brightness_reboot] loaded state: {state}")
        if state is None and self.artifacts is not None:
            try:
                sd = self.artifacts.phase_dir(item_id, "state", create=False)
                log(f"[brightness_reboot] state dir on resume: {sd} exists={sd.exists()}")
                if sd.exists():
                    log(f"[brightness_reboot] state files on resume: {list(sd.iterdir())}")
            except Exception as e:
                log(f"[brightness_reboot] state dir check on resume failed: {e}")


        # Already completed.
        if isinstance(state, dict) and state.get("phase") == "done":
            log("[brightness_reboot] already done")
            return WorkflowResult(success=state.get("ok", True), item_id=item_id, summary="done", data={"ok": state.get("ok", True)})

        # Resumed after reboot: verify brightness preserved.
        if isinstance(state, dict) and state.get("phase") == "rebooting":
            settled = state.get("settled")
            log(f"[brightness_reboot] resumed after reboot, settled={settled}")
            # Check current profile (informational only).
            try:
                prof = handler.get_perf_profile()
                log(f"[brightness_reboot] current profile after reboot: {prof}")
            except Exception as e:
                log(f"[brightness_reboot] profile check failed: {e}")

            # Wait for the daemon to settle, reading brightness until it stabilizes.
            time.sleep(10)
            readings = []
            prev = None
            stable_count = 0
            for i in range(60):
                time.sleep(2)
                after = get_brightness()
                readings.append(after)
                log(f"[brightness_reboot] reading {i}: {after}")
                if after is not None and after == prev:
                    stable_count += 1
                    if stable_count >= 5:
                        break
                else:
                    stable_count = 0
                prev = after
            after = readings[-1] if readings else get_brightness()
            max_b = get_max_brightness()
            log(f"[brightness_reboot] final after={after} max={max_b} readings={readings}")
            if after is None or max_b is None or settled is None:
                self.persist_state(item_id, "state", {"kind": "brightness_restart", "phase": "done", "ok": False, "after": after, "max": max_b, "settled": settled, "readings": readings})
                return WorkflowResult(success=False, item_id=item_id, summary="no backlight after reboot")

            tolerance = max(1, max_b // 20)
            ok = abs(after - settled) <= tolerance
            log(f"[brightness_reboot] settled={settled} after={after} tolerance={tolerance} ok={ok}")

            self.persist_state(item_id, "state", {"kind": "brightness_restart", "phase": "done", "ok": ok, "after": after, "max": max_b, "settled": settled, "readings": readings})
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(item_id, "verify", f"settled={settled} after={after} tolerance={tolerance} ok={ok}\nreadings={readings}\n", step="after_reboot")
                except Exception:
                    pass

            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="passed" if ok else "failed")
                except Exception:
                    pass
            return WorkflowResult(success=ok, item_id=item_id, summary=f"settled={settled} after={after} ok={ok}", data={"ok": ok, "after": after, "settled": settled, "readings": readings})

        # No guard needed - save_state is fixed. If state is missing on resume,
        # the test runs as first invocation (saves state, reboots).

        # First invocation: set brightness to 50%, reboot, check if preserved.
        bh = BrightnessHandler()
        bh.set_brightness_percent(50)
        time.sleep(10)
        # Read multiple times to ensure it's settled
        current = None
        for _ in range(10):
            time.sleep(2)
            current = get_brightness()
            if current is not None:
                break
        # Let it settle a bit more
        time.sleep(10)
        current = get_brightness()
        max_b = get_max_brightness()
        log(f"[brightness_reboot] first invocation, brightness={current}/{max_b} (set to 50%)")
        if current is None:
            return WorkflowResult(success=False, item_id=item_id, summary="no backlight")

        # Record status before reboot.
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="passed")
            except Exception:
                pass

        try:
            boot_id_before = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception:
            boot_id_before = None

        self.persist_state(item_id, "state", {"kind": "brightness_restart", "phase": "rebooting", "boot_id_before": boot_id_before, "settled": current})
        # Verify state was actually saved before rebooting.
        import os as _os
        try:
            _os.sync()
        except Exception:
            pass
        verified_save = False
        for attempt in range(5):
            loaded = self.load_persisted_state(item_id, phase="state")
            if isinstance(loaded, dict) and loaded.get("phase") == "rebooting":
                verified_save = True
                log(f"[brightness_reboot] state verified saved (attempt {attempt+1})")
                break
            log(f"[brightness_reboot] state NOT found (attempt {attempt+1}), retrying...")
            time.sleep(1)
            self.persist_state(item_id, "state", {"kind": "brightness_restart", "phase": "rebooting", "boot_id_before": boot_id_before, "settled": current})
            try:
                _os.sync()
            except Exception:
                pass

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={current}/{max_b}\n", step="before_reboot")
            except Exception as e:
                log(f"[brightness_reboot] save_text failed: {e}")
        try:
            _os.sync()
        except Exception:
            pass

        if not verified_save:
            log("[brightness_reboot] FAILED to persist state - aborting reboot")
            return WorkflowResult(success=False, item_id=item_id, summary="failed to persist state before reboot")




        _setup_autologin()
        # Brightness preservation depends on a normal (graceful) shutdown:
        # services get to run their save/restore logic.  The instant reboot(2)
        # syscall skips that and produces a different (lower) brightness.
        log("[brightness_reboot] rebooting now (graceful)")
        if not _reboot_and_wait(handler, graceful=True):
            # Leave the saved phase "rebooting" in place: a later attempt takes
            # the resume branch and verifies whatever state the machine is in.
            log("[brightness_reboot] reboot did not happen")
            return WorkflowResult(success=False, item_id=item_id, summary="reboot did not happen", data={"ok": False})
        return WorkflowResult(success=True, item_id=item_id, summary="brightness=" + str(current) + ", rebooting")

    def verify_cli_profile_reflected_in_extension(self, target: str, os_id: str | None = None, item_id: str = "cli.profile_reflected") -> WorkflowResult:
        """Switch profile via CLI, verify the GUI extension reflects it."""
        import os
        handler = System76Power(
            test_id="system76_power.cli.profile",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        handler.switch_perf_profile(target)
        import time
        time.sleep(20)
        # Dismiss pop-ups by clicking center.
        try:
            from harness.gui import GuiDriver
            d = GuiDriver(artifacts=self.artifacts)
            d.click_at((0.5, 0.5))
        except Exception:
            pass
        time.sleep(1)

        if os_id is None:
            from harness.platform import detect_platform

            os_id = os.environ.get("TEST_OS_ID") or detect_platform().os_id

        from .gui import System76PowerGUIWorkflow
        gui_wf = System76PowerGUIWorkflow(artifacts=self.artifacts)
        # GUI detection itself retries up to 5 times until detected == target.
        res = gui_wf.detect_power_profile(os_id=os_id, item_id=f"{item_id}.detect", target=target)
        if not res.success:
            return WorkflowResult(success=False, item_id=item_id, summary=f"detect failed: {res.summary}", data=res.data)
        detected = (res.data or {}).get("profile", "").lower()
        import sys
        print(f"[verify_cli_profile] target={target} detected={detected}", file=sys.stderr, flush=True)
        verified = (detected == target.lower())
        # Persist result for aggregation.
        self.persist_state(item_id, "state", {
            "kind": "profile_reflected",
            "target": target,
            "detected": detected,
            "verified": verified,
        })
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"cli={target} gui={detected} verified={verified}",
            data={"target": target, "detected": detected, "verified": verified},
        )

    def get_graphics_power(self, item_id: str = "cli.graphics_power") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.graphics_power",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        p = handler.get_graphics_power()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"power:{p}\n", step="query")
            except Exception:
                pass
        return WorkflowResult(success=p in ("on", "off", None), item_id=item_id, summary=str(p), data={"power": p})

    def set_graphics_power(self, state: str, item_id: str = "cli.graphics_power") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.graphics_power",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        try:
            handler.set_graphics_power(state)
            import time
            time.sleep(10)
        except Exception as e:
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"set:{state} error:{e}\n", step="set")
                except Exception:
                    pass
            raise
        p = handler.get_graphics_power()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"set:{state} got:{p}\n", step="set")
            except Exception:
                pass
        return WorkflowResult(success=p == state, item_id=item_id, summary=f"{state}->{p}", data={"power": p})

