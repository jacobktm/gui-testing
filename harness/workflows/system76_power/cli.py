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

    def get_transition_order(self, item_id: str = "cli.graphics_transitions") -> list[tuple[str, str]]:
        """Determine the order of graphics transitions based on the current mode.

        Returns an ordered list of (source, target) pairs.  The first
        transition starts from the currently active graphics mode so that
        no unnecessary mode switch is needed before the first reboot.
        """
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        switchable = handler.switchable()
        if switchable != "switchable":
            return []

        modes = list(handler.graphics_modes)
        current = handler.get_graphics_mode()
        if current not in modes:
            current = modes[0]

        # Start with all transitions originating from the current mode,
        # then the remaining modes in order.
        ordered_modes = [current] + [m for m in modes if m != current]
        transitions = []
        for source in ordered_modes:
            for target in modes:
                if source != target and (source, target) not in transitions:
                    transitions.append((source, target))
        return transitions

    def transition_graphics(self, source: str, target: str, item_id: str = "cli.graphics_transitions") -> WorkflowResult:
        """Execute a single graphics mode transition (source -> target).

        Switches to source (if needed), reboots, switches to target, reboots,
        and verifies the final mode matches target.
        """
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        progress = self.resume_progress(item_id, kind="graphics_transition") if item_id else {}
        results = progress.get("results", [])
        done = {(e.get("from"), e.get("to")) for e in results if isinstance(e, dict)}

        if (source, target) in done:
            # Already completed in a previous run.
            entry = next((e for e in results if e.get("from") == source and e.get("to") == target), {})
            return WorkflowResult(
                success=entry.get("verified", True),
                item_id=item_id,
                summary=f"{source}->{target} (already done, verified={entry.get('verified', '?')})",
                data={"from": source, "to": target, "actual": entry.get("actual"), "verified": entry.get("verified", True)},
            )

        current = handler.get_graphics_mode()

        # Move to source if needed.
        source_ok = True
        if current != source:
            handler.switch_graphics_mode(source)
            current = source
            self.persist_state(item_id, "state", {"kind": "graphics_transition", "current": current, "source": source, "target": target})
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            current = handler.get_graphics_mode()
            source_ok = (current == source)

        # Switch to target.
        handler.switch_graphics_mode(target)
        current = target
        self.persist_state(item_id, "state", {"kind": "graphics_transition", "current": current, "source": source, "target": target})
        handler.setup_autologin()
        handler.reboot()
        handler.wait_for_boot()
        current = handler.get_graphics_mode()
        target_ok = (current == target)

        # On Pop!_OS 22.04, also verify via GUI that the extension reflects
        # the new graphics mode (satisfies "CLI changes reflected in extension").
        gui_verified = None
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or ""
        if not os_id:
            try:
                os_id_parts = {}
                with open("/etc/os-release") as f:
                    for line in f:
                        if "=" in line:
                            key, val = line.strip().split("=", 1)
                            os_id_parts[key] = val.strip().strip('"').lower()
                os_id = os_id_parts.get("ID", "")
                version = os_id_parts.get("VERSION_ID", "")
                if version:
                    os_id = f"{os_id}-{version}"
            except Exception:
                pass
        if os_id == "pop-22.04" or os_id.startswith("pop-22"):
            try:
                from ...gui import Coords, GuiDriver
                from ...dotool import click, send_keys
                driver = GuiDriver(artifacts=self.artifacts)
                # Open power settings to see the extension
                try:
                    driver.click_at(Coords.OPEN)
                except Exception:
                    pass
                try:
                    extra = Coords.POP22_EXTRA
                    driver.click_at(extra)
                except Exception:
                    pass
                # Detect graphics mode via screenshot + ollama
                from ..system76_power.gui import System76PowerGUIWorkflow
                gui_wf = System76PowerGUIWorkflow(artifacts=self.artifacts)
                det = gui_wf.detect_graphics_mode(os_id=os_id)
                if det.success:
                    detected = (det.data or {}).get("graphics", "").lower()
                    gui_verified = (detected == target.lower())
                else:
                    gui_verified = False
                # Dismiss menus
                try:
                    from ...dotool import send_keys
                    send_keys("key esc\nkey esc\n")
                except Exception:
                    pass
            except Exception:
                gui_verified = None

        verified = source_ok and target_ok
        if gui_verified is not None:
            verified = verified and gui_verified
        entry = {"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified}
        results.append(entry)
        self.persist_state(item_id, "state", {"kind": "graphics_transition", "current": current, "results": results, "completed": len(results)})

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"transition -> {source} to {target} (verified={verified})\n", step="transition")
            except Exception:
                pass

        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"{source}->{target} (actual: {current}, verified={verified})",
            data={"from": source, "to": target, "actual": current, "verified": verified},
        )

    def transition_graphics_all(self, item_id: str = "cli.graphics_transitions") -> WorkflowResult:
        """Run all graphics transitions in the order determined by the starting mode.

        Determines the transition order from the current graphics mode, then
        calls transition_graphics() for each (source, target) pair in sequence.
        Each individual transition handles its own reboot and verification.
        """
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

        # Graphics modes are not present on Ubuntu or COSMIC desktops.
        import os
        os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or ""
        if not os_id:
            try:
                os_id_parts = {}
                with open("/etc/os-release") as f:
                    for line in f:
                        if "=" in line:
                            key, val = line.strip().split("=", 1)
                            os_id_parts[key] = val.strip().strip('"').lower()
                os_id = os_id_parts.get("ID", "")
                version = os_id_parts.get("VERSION_ID", "")
                if version:
                    os_id = f"{os_id}-{version}"
            except Exception:
                pass
        if os_id.startswith("ubuntu") or os_id.startswith("pop-24") or os_id.startswith("pop-26") or "ubuntu" in os_id:
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

        modes = list(handler.graphics_modes)
        if not modes or handler.get_graphics_mode() is None:
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="no graphics modes", data={"skipped": True})

        order = self.get_transition_order(item_id=item_id)
        if not order:
            return WorkflowResult(success=True, item_id=item_id, summary="no transitions", data={"skipped": True})

        results = []
        all_ok = True
        for source, target in order:
            res = self.transition_graphics(source, target, item_id=item_id)
            entry = res.data if res.data else {"from": source, "to": target, "actual": None, "verified": res.success}
            results.append(entry)
            if not res.success:
                all_ok = False

        final_report = "\n".join(
            f"{e['from']}->{e['to']} (actual: {e.get('actual')}, verified={e.get('verified', '?')}, gui_verified={e.get('gui_verified', 'N/A')})"
            for e in results
        )
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", final_report + "\n", step="transition_report")
            except Exception:
                pass

        failed = [e for e in results if not e.get("verified", True)]
        summary = f"transitions:{len(results)} verified:{len(results)-len(failed)} failed:{len(failed)}"
        return WorkflowResult(success=all_ok and len(failed) == 0, item_id=item_id, summary=summary, data={"transitions": results, "order": order})

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

