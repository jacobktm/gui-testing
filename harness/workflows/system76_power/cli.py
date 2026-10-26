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

        # Build adjacency list: all directed edges source -> target.
        adj = {m: [t for t in modes if t != m] for m in modes}
        # Hierholzer's algorithm for Eulerian circuit.
        stack = [current]
        route = []
        while stack:
            v = stack[-1]
            if adj[v]:
                w = adj[v].pop()
                stack.append(w)
            else:
                route.append(stack.pop())
        route.reverse()
        # route is a list of nodes; convert to edges.
        transitions = [(route[i], route[i + 1]) for i in range(len(route) - 1)]
        # Deduplicate while preserving order (Hierholzer may repeat nodes).
        seen = set()
        unique = []
        for edge in transitions:
            if edge not in seen:
                seen.add(edge)
                unique.append(edge)
        print(f"Eulerian circuit: {len(unique)} transitions", flush=True)
        for src, tgt in unique:
            print(f"  {src} -> {tgt}", flush=True)
        return unique

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
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

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

        # --- Phase: start — record source, switch to target, save, reboot ---
        if phase == "start":
            # Log the current mode (source) for reporting.
            actual_source = current if current else source
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

        # --- Phase: rebooting — (after reboot) verify target, record result ---
        if phase in ("rebooting", "done"):
            current = handler.get_graphics_mode()
            verified = (current == target)

            entry = {"from": source, "to": target, "actual": current, "verified": verified}
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
        print(f"Transition order ({len(order)} pairs):", flush=True)
        for src, tgt in order:
            print(f"  {src} -> {tgt}", flush=True)
        if not order:
            return WorkflowResult(success=True, item_id=item_id, summary="no transitions", data={"skipped": True})

        results = []
        all_ok = True
        for source, target in order:
            trans_item_id = f"{item_id}.{source}_to_{target}"
            res = self.transition_graphics(source, target, item_id=trans_item_id)
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

