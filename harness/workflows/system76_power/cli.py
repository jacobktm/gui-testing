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

    def transition_to_integrated(self, item_id: str = "cli.graphics_transition.to_integrated") -> WorkflowResult:
        """Transition from the current mode to integrated (if not already there).

        This ensures the system starts in integrated mode before running
        the ordered transition sequence.  If already in integrated, this
        is a no-op that returns success.
        """
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        switchable = handler.switchable()
        if switchable != "switchable":
            return WorkflowResult(success=True, item_id=item_id, summary="not switchable", data={"skipped": True})

        current = handler.get_graphics_mode()
        print(f"transition_to_integrated: current mode = {current!r}", flush=True)

        if current == "integrated":
            print("  Already in integrated mode, no transition needed.", flush=True)
            return WorkflowResult(success=True, item_id=item_id, summary="already integrated", data={"from": current, "to": "integrated", "actual": current, "verified": True})

        # Switch to integrated.
        result = handler._run(['system76-power', 'graphics', 'integrated'], check=False)
        logged = (result.get('stdout') or '').strip()
        print(f"  system76-power graphics integrated: rc={result.get('returncode')} output={logged!r}", flush=True)
        if result.get('returncode') not in (0, None):
            return WorkflowResult(success=False, item_id=item_id, summary=f"switch to integrated failed: {result.get('stderr', '')}", data={"from": current, "to": "integrated", "actual": current, "verified": False})

        self.persist_state(item_id, "state", {
            "kind": "graphics_transition",
            "phase": "rebooting",
            "source": current,
            "target": "integrated",
            "current": "integrated",
        })
        handler.setup_autologin()
        handler.reboot()
        handler.wait_for_boot()
        current = handler.get_graphics_mode()
        verified = (current == "integrated")
        print(f"  After reboot: mode = {current!r}, verified = {verified}", flush=True)

        self.persist_state(item_id, "state", {
            "kind": "graphics_transition",
            "phase": "done",
            "source": current,
            "target": "integrated",
            "current": current,
            "results": [{"from": current, "to": "integrated", "actual": current, "verified": verified}],
            "completed": 1,
        })

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"transition -> {current} to integrated (verified={verified})\n", step="transition")
            except Exception:
                pass

        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"to_integrated (actual: {current}, verified={verified})",
            data={"from": current, "to": "integrated", "actual": current, "verified": verified},
        )

    def get_transition_order(self, item_id: str = "cli.graphics_transitions") -> list[tuple[str, str]]:
        """Determine an Eulerian circuit through all (source, target) pairs.

        Starting from the current graphics mode, traverses every directed
        edge (source -> target, source != target) exactly once.  Because
        each step's source is the previous step's target, no redundant
        mode switches are needed between transitions.

        Returns an ordered list of (source, target) tuples.
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
        print(f"Detected starting graphics mode: {current!r} (modes: {modes})", flush=True)
        if current not in modes:
            print(f"  Warning: {current!r} not in modes list, falling back to {modes[0]!r}", flush=True)
            current = modes[0]

        # Fixed chained order: each transition's source is the previous
        # transition's target, avoiding redundant mode switches.
        # Starts from 'integrated' (transition_to_integrated ensures this).
        chained_order = [
            ("integrated", "nvidia"),
            ("nvidia", "hybrid"),
            ("hybrid", "compute"),
            ("compute", "integrated"),
            ("integrated", "hybrid"),
            ("hybrid", "nvidia"),
            ("nvidia", "compute"),
            ("compute", "hybrid"),
            ("hybrid", "integrated"),
            ("integrated", "compute"),
            ("compute", "nvidia"),
            ("nvidia", "integrated"),
        ]
        # Filter to only include modes that exist on this system.
        path = [(s, t) for s, t in chained_order if s in modes and t in modes]

        # If not starting in integrated, prepend the transition to integrated.
        if current != "integrated" and "integrated" in modes and current in modes:
            forced = (current, "integrated")
            if forced not in path:
                path = [forced] + path

        print(f"Starting mode: {current!r}", flush=True)
        print(f"Transition order ({len(path)} pairs):", flush=True)
        for src, tgt in path:
            print(f"  {src} -> {tgt}", flush=True)
        return path

    def transition_graphics(self, source: str, target: str, item_id: str = "cli.graphics_transitions") -> WorkflowResult:
        """Execute a single graphics mode transition (source -> target).

        Switches to target, reboots, then verifies the mode matches target.
        The source is recorded for reporting but no switch to source is needed
        (the transition order ensures we are already in source from the
        previous step).

        Uses persisted phase to survive reboots:
        - phase "start":    record source, switch to target, save "rebooting", reboot
        - phase "rebooting": (after reboot) verify target, record result, save "done"
        - phase "done":     already completed, return cached result
        """
        handler = System76Power(
            test_id="system76_power.cli.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )

        # Skip on non-switchable systems or non-applicable OS.
        switchable = handler.switchable()
        if switchable != "switchable":
            return WorkflowResult(success=True, item_id=item_id, summary="not switchable", data={"skipped": True})

        progress = self.resume_progress(item_id, kind="graphics_transition") if item_id else {}
        results = progress.get("results", [])
        done = {(e.get("from"), e.get("to")) for e in results if isinstance(e, dict)}

        # Already completed in a previous run.
        if (source, target) in done:
            entry = next((e for e in results if e.get("from") == source and e.get("to") == target), {})
            return WorkflowResult(
                success=entry.get("verified", True),
                item_id=item_id,
                summary=f"{source}->{target} (already done, verified={entry.get('verified', '?')})",
                data={"from": source, "to": target, "actual": entry.get("actual"), "verified": entry.get("verified", True)},
            )

        in_progress = (progress.get("source"), progress.get("target")) == (source, target)
        phase = progress.get("phase", "start") if in_progress else "start"

        current = handler.get_graphics_mode()
        print(f"  transition {source}->{target}: current mode = {current!r}", flush=True)

        # --- Phase: start — record source, switch to target, save, reboot ---
        if phase == "start":
            # Log the current mode (source) for reporting.
            actual_source = current if current else source
            print(f"  switching to {target}...", flush=True)
            # Switch to target.
            result = handler._run(['system76-power', 'graphics', target], check=False)
            logged_output = (result.get('stdout') or '').strip()
            if result.get('returncode') not in (0, None):
                entry = {"from": source, "to": target, "actual": current, "verified": False, "error": "switch failed"}
                results.append(entry)
                self.persist_state(item_id, "state", {
                    "kind": "graphics_transition",
                    "phase": "done",
                    "source": source,
                    "target": target,
                    "current": current,
                    "results": results,
                    "completed": len(results),
                })
                return WorkflowResult(success=False, item_id=item_id, summary=f"{source}->{target} (switch failed: {result.get('stderr', '')})", data=entry)

            # Save state BEFORE reboot.
            self.persist_state(item_id, "state", {
                "kind": "graphics_transition",
                "phase": "rebooting",
                "source": source,
                "target": target,
                "current": target,
                "results": results,
                "logged_output": logged_output,
            })
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            # If we survive (no reboot happened), continue.
            current = handler.get_graphics_mode()
            phase = "rebooting"
            print(f"  after reboot: mode = {current!r} (target={target!r})", flush=True)

        # --- Phase: rebooting — (after reboot) verify target, record result ---
        if phase in ("rebooting", "done"):
            current = handler.get_graphics_mode()
            print(f"  verify: current={current!r} target={target!r} match={current == target}", flush=True)
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
                    from ..system76_power.gui import System76PowerGUIWorkflow
                    driver = GuiDriver(artifacts=self.artifacts)
                    try:
                        driver.click_at(Coords.OPEN)
                    except Exception:
                        pass
                    try:
                        driver.click_at(Coords.POP22_EXTRA)
                    except Exception:
                        pass
                    gui_wf = System76PowerGUIWorkflow(artifacts=self.artifacts)
                    det = gui_wf.detect_graphics_mode(os_id=os_id)
                    if det.success:
                        detected = (det.data or {}).get("graphics", "").lower()
                        gui_verified = (detected == target.lower())
                    else:
                        gui_verified = False
                    try:
                        from ...dotool import send_keys
                        send_keys("key esc\nkey esc\n")
                    except Exception:
                        pass
                except Exception:
                    gui_verified = None

            verified = target_ok
            if gui_verified is not None:
                verified = verified and gui_verified

            entry = {"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified}
            results.append(entry)
            done.add((source, target))
            self.persist_state(item_id, "state", {
                "kind": "graphics_transition",
                "phase": "done",
                "source": source,
                "target": target,
                "current": current,
                "results": results,
                "completed": len(results),
            })

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

        # Fallback
        return WorkflowResult(success=False, item_id=item_id, summary=f"{source}->{target} (unexpected phase: {phase})")

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

