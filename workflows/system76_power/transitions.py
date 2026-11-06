"""Unified transition workflows.

Single workflow for the repetitive power-profile transitions. All UI
validation goes through UIWorkflow to ensure clicks always happen before
screenshots. (Graphics transitions live in ``graphics_transitions.py`` — a
single phase machine shared by the CLI and GUI drivers.)
"""

from __future__ import annotations

from harness.workflows.base import Workflow, WorkflowResult, rotate_circuit
from harness.workflows.ui_workflow import UIWorkflow
from harness.gui.coords import adjust_coords, get_display_resolution
from harness.platform import get_flavor_for_os_id

#: Closed circuit over the three system76-power performance profiles: all six
#: ordered pairs exactly once, last target == first source, so the walk can
#: be rotated to start from the profile the machine is actually in (no
#: priming ``transition_to_performance`` test needed).
PERF_PROFILE_CIRCUIT: list[tuple[str, str]] = [
    ("performance", "balanced"),
    ("balanced", "battery"),
    ("battery", "performance"),
    ("performance", "battery"),
    ("battery", "balanced"),
    ("balanced", "performance"),
]


def get_perf_profile_chain() -> list[tuple[str, str]]:
    """Profile transition chain rotated to start at the current profile.

    Profile switches are instant (no reboot), so this is recomputed every
    collection — no persisted chain like the graphics one.  A source/current
    mismatch mid-run is harmless: every transition sets and verifies its
    *target*; the source is recorded for reporting only.
    """
    from handlers.system76_power import System76Power

    profile: str | None = None
    try:
        profile = System76Power().get_perf_profile()
    except Exception:
        pass
    return rotate_circuit(PERF_PROFILE_CIRCUIT, profile)


class ProfileTransitionWorkflow(Workflow):
    """UI validation of power profiles (clicks -> screenshot -> LLM)."""

    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.ui = UIWorkflow(artifacts=artifacts)
        from .gui import System76PowerGUIWorkflow
        self.gui_wf = System76PowerGUIWorkflow(artifacts=artifacts)

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
            # App-specific: two center clicks before every open attempt so a
            # lingering open panel can never turn an open click into a close.
            pre_open=self.gui_wf.pre_open_clear,
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
