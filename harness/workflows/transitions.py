"""Unified transition workflows.

Single workflow for each repetitive process (profile transitions, graphics transitions).
All UI validation goes through UIWorkflow to ensure clicks always happen before screenshots.
"""

from __future__ import annotations

import time
from typing import Any

from .base import Workflow, WorkflowResult
from .ui_workflow import UIWorkflow
from ..gui import Coords
from ..gui.coords import adjust_coords, COORD_SOURCE, get_display_resolution
from ..llm.prompts import SETTINGS_SELECTION, SIMPLE_SELECTION, SINGLE_WORD_CHOICE

GRAPHICS_MODE_PROMPT_POP22 = SINGLE_WORD_CHOICE.render(
    context="Pop!_OS 22.04 graphics settings",
    item="graphics mode",
    choices="'integrated', 'hybrid', 'compute', or 'nvidia'",
)
POWER_PROFILE_PROMPT_UBUNTU = SETTINGS_SELECTION.render(
    app_name="power/power mode",
    settings_section="settings",
    item_type="power mode",
    choices="'performance', 'balanced', or 'battery'",
    extra_instructions="If it says 'Power Saver', answer 'battery'. If it says 'Performance', answer 'performance'.",
)
POWER_PROFILE_PROMPT_DEFAULT = SIMPLE_SELECTION.render(
    item="power profile",
    choices="'performance', 'battery', or 'balanced'",
    extra_instructions="Power Saver is the same as 'battery'.",
)


class ProfileTransitionWorkflow(Workflow):
    """Single workflow for all power profile transitions."""

    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.ui = UIWorkflow(artifacts=artifacts)
        from .system76_power.gui import System76PowerGUIWorkflow
        from .system76_power.cli import System76PowerCLIWorkflow
        self.gui_wf = System76PowerGUIWorkflow(artifacts=artifacts)
        self.cli_wf = System76PowerCLIWorkflow(artifacts=artifacts)

    def _get_open_clicks(self, os_id: str) -> list[tuple[float, float]]:
        src = COORD_SOURCE.get(os_id, (1920, 1080))
        dst = get_display_resolution()
        clicks = []
        clicks.append(adjust_coords(Coords.OPEN, src, dst))
        if os_id == "pop-22.04":
            clicks.append(adjust_coords(Coords.POP22_EXTRA, src, dst))
        elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
            extra = Coords.UBUNTU_26.get("extra_click")
            if extra:
                clicks.append(adjust_coords(extra, src, dst))
        return clicks

    def validate_profile(self, target: str, os_id: str = None, item_id: str = "profile.validate") -> WorkflowResult:
        """Validate power profile via UI - clicks to open, takes screenshot, queries LLM."""
        if os_id is None:
            import os
            os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
        clicks = self._get_open_clicks(os_id)
        
        if os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
            expected = {"performance", "balanced", "battery", "power saver", "powersaver"}
            prompt = POWER_PROFILE_PROMPT_UBUNTU
        else:
            expected = {"performance", "balanced", "battery", "battery saver", "batterysaver"}
            prompt = POWER_PROFILE_PROMPT_DEFAULT

        res = self.ui.detect_from_ui(
            clicks=clicks,
            prompt=prompt,
            expected=expected,
            os_id=os_id,
            delay_between_clicks=3.0,
            wait_after_clicks=8.0,
            item_id=item_id,
            max_attempts=5,
        )
        
        if not res.success:
            return res
        
        value = (res.data or {}).get("value", "").lower()
        # Normalize
        if value == "power saver" or value == "battery saver" or value == "batterysaver" or value == "powersaver":
            value = "battery"
        elif value == "high performance":
            value = "performance"
        
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
            import os
            os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
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
            import os
            os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID") or "pop-24.04"
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
        from .system76_power.gui import System76PowerGUIWorkflow
        from .system76_power.cli import System76PowerCLIWorkflow
        self.gui_wf = System76PowerGUIWorkflow(artifacts=artifacts)
        self.cli_wf = System76PowerCLIWorkflow(artifacts=artifacts)

    def _get_open_clicks(self, os_id: str) -> list[tuple[float, float]]:
        src = COORD_SOURCE.get(os_id, (1920, 1080))
        dst = get_display_resolution()
        clicks = []
        clicks.append(adjust_coords(Coords.OPEN, src, dst))
        if os_id == "pop-22.04":
            clicks.append(adjust_coords(Coords.POP22_EXTRA, src, dst))
        return clicks

    def validate_graphics(self, target: str, os_id: str = "pop-22.04", item_id: str = "graphics.validate") -> WorkflowResult:
        """Validate graphics mode via UI - clicks to open, takes screenshot, queries LLM."""
        if not (os_id == "pop-22.04" or os_id.startswith("pop-22")):
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})
        
        clicks = self._get_open_clicks(os_id)
        expected = {"integrated", "hybrid", "compute", "nvidia"}
        prompt = GRAPHICS_MODE_PROMPT_POP22

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
