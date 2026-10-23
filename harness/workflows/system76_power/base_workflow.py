from __future__ import annotations

from handlers.brightness import Brightness
from handlers.system76_power import System76Power

from ..base import Workflow, WorkflowResult


class System76PowerWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.brightness = Brightness()

    def check_profile(self, item_id: str = "cli.power_profile_query_set") -> WorkflowResult:
        handler = System76Power(
            test_id="system76_power.profile",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        profile = handler.get_perf_profile()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="passed" if profile in handler.perf_profiles else "failed")
                self.artifacts.save_text(
                    item_id,
                    "verify",
                    f"queried profile: {profile}\n",
                    step="system76_power_profile",
                )
            except Exception:
                pass
        return WorkflowResult(
            success=profile in handler.perf_profiles,
            item_id=item_id,
            summary=f"profile={profile}",
            data={"profile": profile},
        )

    def check_brightness(self, item_id: str = "power.brightness") -> WorkflowResult:
        b = self.brightness.get_brightness()
        m = self.brightness.get_max_brightness()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(
                    item_id,
                    "verify",
                    f"brightness={b}/{m}\n",
                    step="brightness",
                )
            except Exception:
                pass
        return WorkflowResult(
            success=b is not None and m is not None,
            item_id=item_id,
            summary=f"brightness={b}/{m}",
            data={"brightness": b, "max": m},
        )

