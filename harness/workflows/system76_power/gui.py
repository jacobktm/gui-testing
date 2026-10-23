from __future__ import annotations

from handlers.brightness import Brightness
from handlers.system76_power import System76Power

from ...dotool import click
from ...gui import GuiDriver
from ..base import Workflow, WorkflowResult


class System76PowerGUIWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.driver = GuiDriver(artifacts=artifacts)
        self.brightness = Brightness()

    def open_power_settings(self, os_id: str) -> WorkflowResult:
        """Open power settings via the known click position.

        Pop!_OS 24.04 and Ubuntu 26.04 need only one click at (0.955, 0.014).
        Pop!_OS 22.04 needs an additional click at (0.955, 0.20).
        """
        try:
            try:
                self.driver.click_at((0.955, 0.014))
            except Exception:
                pass
            if os_id == "pop-22.04":
                try:
                    extra = getattr(self, "pop22_extra_click", (0.955, 0.20))
                    self.driver.click_at(extra)
                except Exception:
                    pass
        except Exception as exc:
            return WorkflowResult(
                success=False,
                item_id="gui.power_settings_open",
                summary=f"failed: {exc}",
            )

        return WorkflowResult(
            success=True,
            item_id="gui.power_settings_open",
            summary="opened power settings",
            data={"os_id": os_id},
        )

    def detect_power_profile(
        self,
        os_id: str,
        item_id: str = "gui.power_profile_detect",
    ) -> WorkflowResult:
        """Detect current power profile via UI.

        Ubuntu uses 'Power Saver' label; others use battery/balanced/performance.
        """
        if os_id == "ubuntu-26.04":
            expected = {"Power Saver", "Balanced", "Performance"}
            prompt = (
                "Look at this screenshot of Ubuntu 26.04 power settings. "
                "What power mode is currently active? "
                "Give me the response in just a single word: either "
                "'Power Saver', 'Balanced', or 'Performance'."
            )
        else:
            expected = {"battery", "balanced", "performance"}
            prompt = (
                "Look at this screenshot of the power settings. "
                "What power profile is currently active? "
                "Give me the response in just a single word, either "
                "'battery', 'balanced', or 'performance'."
            )

        try:
            value, result = self.driver.capture_and_detect(
                prompt,
                expected,
                item_id=item_id,
                phase="detect",
                step="power_profile",
            )
        except Exception as exc:
            return WorkflowResult(
                success=False, item_id=item_id, summary=f"detect failed: {exc}"
            )

        if self.artifacts is not None and item_id:
            try:
                ok = value in expected or value.lower() in {e.lower() for e in expected}
                self.artifacts.record_item(item_id, status="passed" if ok else "failed")
            except Exception:
                pass

        return WorkflowResult(
            success=value in expected or value.lower() in {e.lower() for e in expected},
            item_id=item_id,
            summary=f"profile={value}",
            data={"profile": value, "normalized": result.normalized},
        )

    def detect_graphics_mode(
        self,
        item_id: str = "gui.graphics_mode_pop22",
    ) -> WorkflowResult:
        """Detect graphics mode on Pop!_OS 22.04 only."""
        expected = {"integrated", "hybrid", "compute", "nvidia"}
        prompt = (
            "Look at this screenshot of Pop!_OS 22.04 graphics settings. "
            "What graphics mode is currently selected/active? "
            "Give me the response in just a single word: either "
            "'integrated', 'hybrid', 'compute', or 'nvidia'."
        )

        try:
            value, result = self.driver.capture_and_detect(
                prompt,
                expected,
                item_id=item_id,
                phase="detect",
                step="graphics_mode",
            )
        except Exception as exc:
            return WorkflowResult(
                success=False, item_id=item_id, summary=f"detect failed: {exc}"
            )

        if self.artifacts is not None and item_id:
            try:
                ok = value.lower() in expected
                self.artifacts.record_item(item_id, status="passed" if ok else "failed")
            except Exception:
                pass

        return WorkflowResult(
            success=value.lower() in expected,
            item_id=item_id,
            summary=f"graphics={value}",
            data={"graphics": value, "normalized": result.normalized},
        )

    def ensure_max_brightness(self, item_id: str = "gnome.brightness_setup") -> WorkflowResult:
        max_b = self.brightness.get_max_brightness()
        if max_b is None:
            return WorkflowResult(success=False, item_id=item_id, summary="no backlight")
        ok = self.brightness.set_brightness(max_b)
        b = self.brightness.get_brightness()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={b}/{max_b}\n", step="max_brightness")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}/{max_b}", data={"brightness": b, "max": max_b})

    def set_brightness_max(self, item_id: str = "gnome.brightness_max") -> WorkflowResult:
        return self.ensure_max_brightness(item_id=item_id)

    def set_brightness_min(self, item_id: str = "gnome.brightness_min") -> WorkflowResult:
        ok = self.brightness.set_brightness(0) if hasattr(self.brightness, 'set_brightness') else False
        # try setting to lowest
        try:
            if self.brightness.backlight:
                (self.brightness.backlight / "brightness").write_text("0")
                ok = True
        except Exception:
            ok = False
        b = self.brightness.get_brightness()
        m = self.brightness.get_max_brightness()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={b}/{m}\n", step="min_brightness")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}/{m}", data={"brightness": b, "max": m})

    def get_brightness(self, item_id: str = "gnome.brightness_get") -> WorkflowResult:
        b = self.brightness.get_brightness()
        m = self.brightness.get_max_brightness()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"brightness={b}/{m}\n", step="brightness")
            except Exception:
                pass
        return WorkflowResult(success=b is not None, item_id=item_id, summary=f"{b}/{m}", data={"brightness": b, "max": m})

    def save_brightness(self, item_id: str = "gnome.brightness_save") -> WorkflowResult:
        path = self.brightness.save_state()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"saved:{path}\n", step="save")
            except Exception:
                pass
        return WorkflowResult(success=path is not None, item_id=item_id, summary=str(path), data={"path": str(path) if path else None})

    def restore_brightness(self, item_id: str = "gnome.brightness_restore") -> WorkflowResult:
        ok = self.brightness.restore_state()
        b = self.brightness.get_brightness()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"restored brightness={b}\n", step="restore")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}", data={"brightness": b})



