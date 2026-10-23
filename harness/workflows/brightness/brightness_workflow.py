from __future__ import annotations

from handlers.brightness import Brightness

from ..base import Workflow, WorkflowResult


class BrightnessWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.brightness = Brightness()

    def set_max(self, item_id: str = "brightness.set_max") -> WorkflowResult:
        max_b = self.brightness.get_max_brightness()
        if max_b is None:
            return WorkflowResult(success=False, item_id=item_id, summary="no backlight")
        ok = self.brightness.set_brightness(max_b)
        if self.artifacts and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={self.brightness.get_brightness()}\n", step="set_max")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"max={max_b}")

    def set_percent(self, percent: int, item_id: str = "brightness.set") -> WorkflowResult:
        ok = self.brightness.set_brightness_percent(percent)
        if self.artifacts and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={self.brightness.get_brightness()}\n", step=f"set_{percent}")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"{percent}%")

    def get_brightness(self, item_id: str = "brightness.get") -> WorkflowResult:
        b = self.brightness.get_brightness()
        m = self.brightness.get_max_brightness()
        if self.artifacts and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"brightness={b}/{m}\n", step="get")
            except Exception:
                pass
        return WorkflowResult(success=b is not None, item_id=item_id, summary=f"{b}/{m}", data={"brightness": b, "max": m})
