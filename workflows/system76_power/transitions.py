"""Unified transition workflows.

Single workflow for each repetitive process (profile transitions, graphics transitions).
All UI validation goes through UIWorkflow to ensure clicks always happen before screenshots.
"""

from __future__ import annotations

import time
from typing import Any

from harness.workflows.base import Workflow, WorkflowResult
from harness.workflows.ui_workflow import UIWorkflow
from harness.gui.coords import adjust_coords, get_display_resolution
from harness.platform import get_flavor_for_os_id


class ProfileTransitionWorkflow(Workflow):
    """Single workflow for all power profile transitions."""

    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.ui = UIWorkflow(artifacts=artifacts)
        from .gui import System76PowerGUIWorkflow
        from .cli import System76PowerCLIWorkflow
        self.gui_wf = System76PowerGUIWorkflow(artifacts=artifacts)
        self.cli_wf = System76PowerCLIWorkflow(artifacts=artifacts)

    def _get_open_clicks(self, os_id: str) -> list[tuple[float, float]]:
        flavor = get_flavor_for_os_id(os_id)
        src = flavor.get_coord_source()
        dst = get_display_resolution()
        clicks = [adjust_coords(c, src, dst) for c in flavor.get_open_clicks()]
        clicks.extend(adjust_coords(c, src, dst) for c in flavor.get_extra_clicks())
        return clicks

    def validate_profile(self, target: str, os_id: str = None, item_id: str = "profile.validate") -> WorkflowResult:
        """Validate power profile via UI - clicks to open, takes screenshot, queries LLM."""
        if os_id is None:
            from harness.platform import detect_platform

            os_id = detect_platform().os_id
        clicks = self._get_open_clicks(os_id)
        flavor = get_flavor_for_os_id(os_id)
        expected = flavor.get_profile_expected()
        prompt = flavor.get_profile_prompt()

        res = self.ui.detect_from_ui(
            clicks=clicks,
            prompt=prompt,
            expected=expected,
            os_id=os_id,
            delay_between_clicks=flavor.get_click_delay(),
            wait_after_clicks=flavor.get_wait_after_clicks(),
            item_id=item_id,
            max_attempts=5,
        )
        
        if not res.success:
            return res
        
        value = (res.data or {}).get("value", "")
        value = flavor.normalize_profile(value)
        
        verified = (value == target.lower())
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"detected={value} target={target} verified={verified}",
            data={"value": value, "target": target, "verified": verified},
        )

    def transition_to(self, target: str, os_id: str = None, via: str = "gui", item_id: str = None) -> WorkflowResult:
        """Single workflow to transition to target profile via GUI or CLI."""
        if os_id is None:
            from harness.platform import detect_platform

            os_id = detect_platform().os_id
        if item_id is None:
            item_id = f"{via}.power_profile_transition.to_{target}"
        
        from handlers.system76_power import System76Power
        handler = System76Power(artifacts=self.artifacts)
        
        if via == "cli":
            handler.switch_perf_profile(target)
            import time
            time.sleep(25)
            return self.validate_profile(target, os_id=os_id, item_id=f"{item_id}.validate")
        else:
            current = handler.get_perf_profile()
            res = self.gui_wf.transition_perf_profile(current or "performance", target, os_id=os_id, item_id=item_id)
            return res

    def run_all_gui(self, os_id: str = "pop-22.04", item_id: str = "gui.power_profile_transitions_all") -> WorkflowResult:
        """Run all GUI profile transitions in order."""
        order = ["balanced", "battery", "performance", "battery", "balanced", "performance"]
        results = []
        all_ok = True
        for tgt in order:
            res = self.transition_to(tgt, os_id=os_id, via="gui", item_id=f"{item_id}.to_{tgt}")
            results.append({"to": tgt, "success": res.success, "data": res.data})
            if not res.success:
                all_ok = False
        return WorkflowResult(
            success=all_ok,
            item_id=item_id,
            summary=f"ran {len(order)} transitions, all_ok={all_ok}",
            data={"results": results},
        )

    def run_all_cli_validate(self, os_id: str = None, item_id: str = "cli.profile_reflected_all") -> WorkflowResult:
        """Run all CLI profile changes and validate reflection via UI workflow."""
        if os_id is None:
            from harness.platform import detect_platform

            os_id = detect_platform().os_id
        from handlers.system76_power import System76Power
        handler = System76Power()
        handler.switch_perf_profile("performance")
        import time
        time.sleep(20)
        
        order = ["balanced", "battery", "performance", "battery", "balanced", "performance"]
        results = []
        all_ok = True
        for tgt in order:
            handler.switch_perf_profile(tgt)
            time.sleep(25)
            val = self.validate_profile(tgt, os_id=os_id, item_id=f"{item_id}.to_{tgt}")
            results.append({"to": tgt, "validated": val.success, "data": val.data})
            if not val.success:
                all_ok = False
        return WorkflowResult(
            success=all_ok,
            item_id=item_id,
            summary=f"validated {len(order)} CLI profile changes, all_ok={all_ok}",
            data={"results": results},
        )


class GraphicsTransitionWorkflow(Workflow):
    """Single workflow for all graphics mode transitions."""

    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.ui = UIWorkflow(artifacts=artifacts)
        from .gui import System76PowerGUIWorkflow
        from .cli import System76PowerCLIWorkflow
        self.gui_wf = System76PowerGUIWorkflow(artifacts=artifacts)
        self.cli_wf = System76PowerCLIWorkflow(artifacts=artifacts)

    def _get_open_clicks(self, os_id: str) -> list[tuple[float, float]]:
        flavor = get_flavor_for_os_id(os_id)
        src = flavor.get_coord_source()
        dst = get_display_resolution()
        clicks = [adjust_coords(c, src, dst) for c in flavor.get_open_clicks()]
        clicks.extend([adjust_coords(c, src, dst) for c in flavor.get_extra_clicks()])
        return clicks

    def validate_graphics(self, target: str, os_id: str = "pop-22.04", item_id: str = "graphics.validate") -> WorkflowResult:
        """Validate graphics mode via UI - clicks to open, takes screenshot, queries LLM."""
        flavor = get_flavor_for_os_id(os_id)
        if not flavor.supports_graphics_switching():
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})
        
        clicks = self._get_open_clicks(os_id)
        expected = flavor.get_graphics_expected()
        prompt = flavor.get_graphics_prompt()

        res = self.ui.detect_from_ui(
            clicks=clicks,
            prompt=prompt,
            expected=expected,
            os_id=os_id,
            delay_between_clicks=3.0,
            wait_after_clicks=10.0,
            item_id=item_id,
            max_attempts=5,
        )
        
        if not res.success:
            return res
        
        value = (res.data or {}).get("value", "").lower()
        verified = (value == target.lower())
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"detected={value} target={target} verified={verified}",
            data={"value": value, "target": target, "verified": verified},
        )

    def transition_to(self, target: str, os_id: str = "pop-22.04", via: str = "cli", item_id: str = None) -> WorkflowResult:
        """Single workflow to transition to target graphics mode."""
        if item_id is None:
            item_id = f"{via}.graphics_transition.to_{target}"
        if via == "cli":
            return self.cli_wf.transition_to_hybrid() if target == "hybrid" else self.cli_wf.set_graphics(target, item_id=item_id)
        else:
            return self.gui_wf.transition_graphics("hybrid", target, os_id=os_id, item_id=item_id)

    def run_all_cli(self, item_id: str = "cli.graphics_transitions_all") -> WorkflowResult:
        """Run all CLI graphics transitions."""
        order = self.cli_wf.get_transition_order(item_id=item_id)
        results = []
        all_ok = True
        for src, tgt in order:
            res = self.cli_wf.transition_graphics(src, tgt, item_id=f"{item_id}.to_{tgt}")
            results.append({"to": tgt, "success": res.success, "data": res.data})
            if not res.success:
                all_ok = False
        return WorkflowResult(
            success=all_ok,
            item_id=item_id,
            summary=f"ran {len(order)} transitions, all_ok={all_ok}",
            data={"results": results, "order": order},
        )

    def run_all_gui(self, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transitions_all") -> WorkflowResult:
        """Run all GUI graphics transitions."""
        res = self.gui_wf.transition_graphics_all(os_id=os_id, item_id=item_id)
        return res
