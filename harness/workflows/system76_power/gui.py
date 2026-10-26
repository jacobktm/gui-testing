from __future__ import annotations

from harness.brightness import BrightnessHandler
from handlers.system76_power import System76Power

from ...dotool import click, send_keys
from ...gui import Coords, GuiDriver
from ..base import Workflow, WorkflowResult


class System76PowerGUIWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.driver = GuiDriver(artifacts=artifacts)
        self.brightness = BrightnessHandler()

    def open_power_settings(self, os_id: str) -> WorkflowResult:
        """Open power settings via the known click position."""
        try:
            try:
                self.driver.click_at(Coords.OPEN)
            except Exception:
                pass
            if os_id == "pop-22.04":
                try:
                    extra = getattr(self, "pop22_extra_click", Coords.POP22_EXTRA)
                    self.driver.click_at(extra)
                except Exception:
                    pass
            elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
                try:
                    extra = getattr(self, "ubuntu_extra_click", Coords.UBUNTU_26.get("extra_click"))
                    if extra:
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

    def dismiss_menus(self):
        try:
            send_keys("key esc\nkey esc\n")
        except Exception:
            try:
                self.driver.click_at((0.1, 0.1))
                self.driver.click_at((0.1, 0.1))
            except Exception:
                pass


    def set_power_profile_gui(self, profile: str, os_id: str, item_id: str = "gui.power_profile_switch") -> WorkflowResult:
        try:
            self.open_power_settings(os_id)
            if os_id == "pop-22.04":
                coords = Coords.POP22_PROFILES.get(profile)
            elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
                coords = Coords.UBUNTU_26.get(f"profile_{profile}")
            else:
                coords = getattr(Coords, "POP_24", {}).get(f"profile_{profile}")
            if coords:
                self.driver.click_at(coords)
            if os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
                self.dismiss_menus()
            if self.artifacts and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"set profile {profile}\n", step="set")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary=f"profile {profile}", data={"profile": profile})
        except Exception as exc:
            return WorkflowResult(success=False, item_id=item_id, summary=str(exc))


    def set_graphics_mode_gui(self, mode: str, os_id: str = "pop-22.04", item_id: str = "gui.graphics_switch") -> WorkflowResult:
        try:
            self.open_power_settings(os_id)
            if os_id == "pop-22.04":
                coords = Coords.POP22_GRAPHICS.get(mode)
                if coords:
                    self.driver.click_at(coords)
            if self.artifacts and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"set graphics {mode}\n", step="set")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary=f"graphics {mode}", data={"graphics": mode})
        except Exception as exc:
            return WorkflowResult(success=False, item_id=item_id, summary=str(exc))


    def transition_graphics_all(self, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transitions") -> WorkflowResult:
        """Transition graphics modes via GUI clicks, rebooting between transitions.

        Pop!_OS 22.04 is the only release that transitions graphics modes
        graphically; other releases rely on the CLI workflow.
        """
        handler = System76Power(
            test_id="system76_power.gui.graphics",
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
        transitions = [
            (source, target)
            for source in modes
            for target in modes
            if source != target
        ]

        # Resume progress from a previous boot: completed pairs are skipped and
        # their results are carried into the final report.
        progress = self.resume_progress(item_id, kind="graphics_transition") if item_id else {}
        results = [
            entry
            for entry in (progress.get("results") or [])
            if isinstance(entry, dict) and entry.get("from") in modes and entry.get("to") in modes
        ]
        done = {(entry.get("from"), entry.get("to")) for entry in results}
        current = handler.get_graphics_mode()
        persisted_mode = progress.get("current")
        # Prefer the mode reported by the hardware after the reboot; the stored
        # value is only a fallback when the query is unavailable.
        if current not in modes and isinstance(persisted_mode, str) and persisted_mode in modes:
            current = persisted_mode

        def save_progress() -> None:
            self.persist_state(
                item_id,
                "state",
                {
                    "kind": "graphics_transition",
                    "current": current,
                    "results": results,
                    "completed": len(results),
                },
            )

        for source, target in transitions:
            if (source, target) in done:
                continue
            if current != source:
                self.set_graphics_mode_gui(source, os_id=os_id, item_id=f"{item_id}.nav")
                current = source
                save_progress()
                handler.setup_autologin()
                handler.reboot()
                handler.wait_for_boot()
                current = handler.get_graphics_mode()
            self.set_graphics_mode_gui(target, os_id=os_id, item_id=item_id)
            current = target
            save_progress()
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            current = handler.get_graphics_mode()
            results.append({"from": source, "to": target, "actual": current})
            done.add((source, target))
            save_progress()

        final_report = "\n".join(
            f"{entry['from']}->{entry['to']} (actual: {entry['actual']})"
            for entry in results
        )
        save_progress()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", final_report + "\n", step="transition_report")
            except Exception:
                pass
        return WorkflowResult(success=True, item_id=item_id, summary=f"transitions:{len(results)}", data={"transitions": results})


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
        os_id: str = "pop-22.04",
        item_id: str = "gui.graphics_mode_detect",
    ) -> WorkflowResult:
        """Detect graphics mode via UI for the given OS."""
        expected = {"integrated", "hybrid", "compute", "nvidia"}
        if os_id == "pop-22.04":
            prompt = (
                "Look at this screenshot of Pop!_OS 22.04 graphics settings. "
                "What graphics mode is currently selected/active? "
                "Give me the response in just a single word: either "
                "'integrated', 'hybrid', 'compute', or 'nvidia'."
            )
        elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
            expected = {"integrated", "hybrid", "compute", "nvidia", "performance"}
            prompt = (
                "Look at this screenshot of Ubuntu power settings. "
                "What graphics mode is currently selected/active? "
                "Give me the response in just a single word: either "
                "'integrated', 'hybrid', 'compute', or 'nvidia'."
            )
        else:
            # Pop!_OS 24.04 / COSMIC
            expected = {"integrated", "hybrid", "compute", "nvidia"}
            prompt = (
                "Look at this screenshot of the power settings. "
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
        max_b = self.brightness.maximum()
        if max_b is None:
            return WorkflowResult(success=False, item_id=item_id, summary="no backlight")
        ok = self.brightness.brightness_up_to_max()
        b = self.brightness.current()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={b}/{max_b}\n", step="max_brightness")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}/{max_b}", data={"brightness": b, "max": max_b})

    def set_brightness_max(self, item_id: str = "gnome.brightness_max") -> WorkflowResult:
        return self.ensure_max_brightness(item_id=item_id)

    def set_brightness_min(self, item_id: str = "gnome.brightness_min") -> WorkflowResult:
        ok = self.brightness.brightness_down_to_min()
        b = self.brightness.current()
        m = self.brightness.maximum()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={b}/{m}\n", step="min_brightness")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}/{m}", data={"brightness": b, "max": m})

    def get_brightness(self, item_id: str = "gnome.brightness_get") -> WorkflowResult:
        b = self.brightness.current()
        m = self.brightness.maximum()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"brightness={b}/{m}\n", step="brightness")
            except Exception:
                pass
        return WorkflowResult(success=b is not None, item_id=item_id, summary=f"{b}/{m}", data={"brightness": b, "max": m})




