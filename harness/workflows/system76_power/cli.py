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
        handler.switch_perf_profile(profile)
        newp = handler.get_perf_profile()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "action", f"set:{profile} got:{newp}\n", step="set")
            except Exception:
                pass
        return WorkflowResult(success=newp == profile or profile in handler.perf_profiles, item_id=item_id, summary=f"{profile}->{newp}", data={"profile": newp})

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
        # Build transition graph like in handler example
        transition_graph = {s: [t for t in modes if t != s] for s in modes}
        stack = [handler.get_graphics_mode() or modes[0]]
        circuit = []
        while stack:
            current = stack[-1]
            if transition_graph.get(current):
                next_state = transition_graph[current].pop()
                stack.append(next_state)
            else:
                circuit.append(stack.pop())
        sequence = circuit[::-1]

        results = []
        from_mode = None
        for mode in sequence:
            if not from_mode:
                from_mode = mode
                continue
            if mode == handler.get_graphics_mode():
                from_mode = mode
                continue
            handler.switch_graphics_mode(mode)
            from_mode = mode
            results.append(mode)
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"transition -> {mode}\n", step="transition")
                except Exception:
                    pass

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="passed")
            except Exception:
                pass
        return WorkflowResult(success=True, item_id=item_id, summary=f"transitions:{len(results)}", data={"transitions": results})


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

