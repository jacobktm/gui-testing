from __future__ import annotations

from handlers.system76_power import System76Power

from ..base import Workflow, WorkflowResult


class System76PowerCLIWorkflow(Workflow):
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

    def query_switchable(self, item_id: str = "cli.laptop_switchable_graphics_can_be_queried") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.switchable",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        switchable = handler.switchable()
        if self.artifacts is not None and item_id:
            try:
                ok = switchable in ("switchable", "not switchable")
                self.artifacts.record_item(item_id, status="passed" if ok else "failed")
                self.artifacts.save_text(item_id, "verify", f"switchable: {switchable}\n", step="query")
            except Exception:
                pass
        return WorkflowResult(success=switchable in ("switchable", "not switchable"), item_id=item_id, summary=switchable, data={"switchable": switchable})

    def set_graphics(self, mode: str, item_id: str = "cli.graphics_switch") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        handler.switch_graphics_mode(mode)
        newm = handler.get_graphics_mode()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"set:{mode} got:{newm}\n", step="set")
            except Exception:
                pass
        return WorkflowResult(success=True, item_id=item_id, summary=f"{mode}->{newm}", data={"graphics": newm})

    def transition_graphics_all(self, item_id: str = "cli.graphics_transitions") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        switchable = handler.switchable()
        if switchable != "switchable":
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not switchable", data={"skipped": True})

        modes = list(handler.graphics_modes)
        # Exercise every ordered pair of graphics modes (source -> target).
        transitions = [
            (source, target)
            for source in modes
            for target in modes
            if source != target
        ]

        # Resume progress from a previous boot: completed pairs are skipped and
        # their results are carried into the final report.
        progress = self.resume_progress(item_id, kind="graphics_transition") if item_id else {}
        results = [
            entry
            for entry in (progress.get("results") or [])
            if isinstance(entry, dict) and entry.get("from") in modes and entry.get("to") in modes
        ]
        done = {(entry.get("from"), entry.get("to")) for entry in results}
        current = handler.get_graphics_mode()
        persisted_mode = progress.get("current")
        # Prefer the mode reported by the hardware after the reboot; the stored
        # value is only a fallback when the query is unavailable.
        if current not in modes and isinstance(persisted_mode, str) and persisted_mode in modes:
            current = persisted_mode

        def save_progress() -> None:
            self.persist_state(
                item_id,
                "state",
                {
                    "kind": "graphics_transition",
                    "current": current,
                    "results": results,
                    "completed": len(results),
                },
            )

        for source, target in transitions:
            if (source, target) in done:
                continue
            # Move to the source mode before exercising source -> target.
            if current != source:
                handler.switch_graphics_mode(source)
                current = source
                save_progress()
                handler.setup_autologin()
                handler.reboot()
                handler.wait_for_boot()
                current = handler.get_graphics_mode()
            handler.switch_graphics_mode(target)
            current = target
            save_progress()
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            current = handler.get_graphics_mode()
            results.append({"from": source, "to": target, "actual": current})
            done.add((source, target))
            save_progress()
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"transition -> {source} to {target}\n", step="transition")
                except Exception:
                    pass

        final_report = "\n".join(
            f"{entry['from']}->{entry['to']} (actual: {entry['actual']})"
            for entry in results
        )
        save_progress()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", final_report + "\n", step="transition_report")
            except Exception:
                pass
        return WorkflowResult(success=True, item_id=item_id, summary=f"transitions:{len(results)}", data={"transitions": results})


    def check_brightness_after_reboot(self, item_id: str = "cli.brightness_restart") -> WorkflowResult:
        """Verify screen brightness is preserved across a system reboot.

        First invocation saves the current brightness and reboots.  The resumed
        invocation (after boot) reads the brightness again and compares it to
        the saved value.
        """
        from harness.brightness import get_brightness

        handler = System76Power(
            test_id="system76_power.cli.brightness_restart",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )

        progress = self.resume_progress(item_id, kind="brightness_restart") if item_id else {}
        phase = progress.get("phase", "before")

        if phase == "before":
            # First invocation: save brightness and reboot.
            before = get_brightness()
            if before is None:
                return WorkflowResult(success=False, item_id=item_id, summary="no backlight")
            self.persist_state(
                item_id,
                "state",
                {"kind": "brightness_restart", "before": before, "phase": "before"},
            )
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(item_id, "setup", f"brightness_before={before}\n", step="before_reboot")
                except Exception:
                    pass
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            # Process is killed by reboot; resumed run handles the comparison.
            return WorkflowResult(success=True, item_id=item_id, summary=f"saved={before}, rebooting")

        # Resumed invocation: compare brightness after reboot.
        before = progress.get("before")
        after = get_brightness()
        if before is None or after is None:
            return WorkflowResult(success=False, item_id=item_id, summary=f"before={before} after={after}")

        # Allow small tolerance (backlight may shift by a step).
        max_b = None
        try:
            from harness.brightness import get_max_brightness
            max_b = get_max_brightness()
        except Exception:
            pass
        tolerance = max(1, (max_b or 100) // 20)
        ok = abs(after - before) <= tolerance

        self.persist_state(
            item_id,
            "state",
            {"kind": "brightness_restart", "before": before, "after": after, "phase": "done"},
        )
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"before={before} after={after} ok={ok}\n", step="after_reboot")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"before={before} after={after}", data={"before": before, "after": after})

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
        handler.set_graphics_power(state)
        p = handler.get_graphics_power()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"set:{state} got:{p}\n", step="set")
            except Exception:
                pass
        return WorkflowResult(success=p == state, item_id=item_id, summary=f"{state}->{p}", data={"power": p})

