from __future__ import annotations

from harness.brightness import BrightnessHandler
from handlers.system76_power import System76Power

from ...gui import Coords, GuiDriver
from ...gui.coords import adjust_coords, COORD_SOURCE
from ..base import Workflow, WorkflowResult


class System76PowerGUIWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.driver = GuiDriver(artifacts=artifacts)
        self.brightness = BrightnessHandler()

    def open_power_settings(self, os_id: str) -> WorkflowResult:
        """Open power settings via adjusted hardcoded click positions."""
        import sys
        import time
        _src = COORD_SOURCE.get(os_id, (1920, 1080))
        try:
            # Click the system tray / battery icon.
            self.driver.click_at(adjust_coords(Coords.OPEN, _src))
            if os_id == "pop-22.04":
                time.sleep(2)
                extra = getattr(self, "pop22_extra_click", Coords.POP22_EXTRA)
                self.driver.click_at(adjust_coords(extra, _src))
            elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
                time.sleep(2)
                extra = getattr(self, "ubuntu_extra_click", Coords.UBUNTU_26.get("extra_click"))
                if extra:
                    self.driver.click_at(adjust_coords(extra, _src))
            # Pop 24 (COSMIC): single click on battery icon opens settings.
            time.sleep(3)
        except Exception as exc:
            print(f"[open_power_settings] FAILED: {exc}", file=sys.stderr, flush=True)
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

    def transition_to_performance(self, os_id: str = "pop-22.04", item_id: str = "gui.power_profile_transition.to_performance") -> WorkflowResult:
        """Ensure starting from performance profile (known starting point)."""
        from handlers.system76_power import System76Power
        handler = System76Power(artifacts=self.artifacts)
        current = handler.get_perf_profile()
        if current == "performance":
            return WorkflowResult(success=True, item_id=item_id, summary="already performance", data={"profile": "performance"})
        res = self.set_power_profile_gui("performance", os_id=os_id, item_id=item_id)
        if not res.success:
            return res
        import time
        time.sleep(2)
        handler2 = System76Power(artifacts=self.artifacts)
        actual = handler2.get_perf_profile()
        verified = (actual == "performance")
        return WorkflowResult(success=verified, item_id=item_id, summary=f"to_performance (actual: {actual})", data={"profile": actual, "verified": verified})

    def transition_perf_profile(self, source: str, target: str, os_id: str = "pop-22.04", item_id: str = "gui.power_profile_transition") -> WorkflowResult:
        """Transition from source to target power profile via GUI and verify CLI+GUI agreement."""
        import sys
        print(f"[transition_perf_profile] {source}->{target} os_id={os_id}", file=sys.stderr, flush=True)
        from handlers.system76_power import System76Power
        res = self.set_power_profile_gui(target, os_id=os_id, item_id=item_id)
        print(f"[transition_perf_profile] set_power_profile_gui: success={res.success} summary={res.summary}", file=sys.stderr, flush=True)
        if not res.success:
            return res
        import time
        time.sleep(3)
        handler = System76Power(artifacts=self.artifacts)
        actual = handler.get_perf_profile()
        print(f"[transition_perf_profile] CLI profile after: {actual} (target={target})", file=sys.stderr, flush=True)
        verified = (actual == target)
        # Also verify via GUI detection
        gui_verified = None
        try:
            det = self.detect_power_profile(os_id=os_id)
            if det.success:
                detected = (det.data or {}).get("profile", "").lower()
                gui_verified = (detected == target.lower())
        except Exception:
            gui_verified = None
        if gui_verified is not None:
            verified = verified and gui_verified
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"{source}->{target} (cli={actual}, gui={gui_verified})",
            data={"from": source, "to": target, "cli": actual, "gui_verified": gui_verified, "verified": verified},
        )

    def dismiss_menus(self):
        # Click at center to dismiss lingering dialogs/pop-ups.
        # ESC doesn't work on COSMIC; center click always works.
        # Do NOT click at (0.1, 0.1) — that activates UI elements.
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        import time
        time.sleep(1.0)
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass


    def set_power_profile_gui(self, profile: str, os_id: str, item_id: str = "gui.power_profile_switch") -> WorkflowResult:
        import sys
        try:
            print(f"[set_power_profile_gui] profile={profile} os_id={os_id}", file=sys.stderr, flush=True)
            self.open_power_settings(os_id)
            import time
            time.sleep(5)
            if os_id == "pop-22.04":
                raw_coords = Coords.POP22_PROFILES.get(profile)
            elif os_id == "ubuntu-26.04" or os_id.startswith("ubuntu"):
                raw_coords = Coords.UBUNTU_26.get(f"profile_{profile}")
            else:
                raw_coords = getattr(Coords, "POP_24", {}).get(f"profile_{profile}")
            # Adjust for display aspect ratio.
            src = COORD_SOURCE.get(os_id, (1920, 1080))
            coords = adjust_coords(raw_coords, src) if raw_coords else None
            print(f"[set_power_profile_gui] raw={raw_coords} adjusted={coords} src={src}", file=sys.stderr, flush=True)
            if coords:
                import sys
                print(f"[set_power_profile_gui] clicking profile {profile} at {coords}", file=sys.stderr, flush=True)
                # Click the profile coordinate twice to ensure registration.
                self.driver.click_at(coords)
                print(f"[set_power_profile_gui] first click done", file=sys.stderr, flush=True)
                time.sleep(1)
                self.driver.click_at(coords)
                print(f"[set_power_profile_gui] second click done", file=sys.stderr, flush=True)
                time.sleep(1)
            # Dismiss any pop-up/notification.
            self.dismiss_menus()
            # Click center screen once to dismiss pop-ups.
            try:
                self.driver.go_to((0.5, 0.5))
                self.driver.click_at((0.5, 0.5))
            except Exception:
                pass
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
                raw_coords = Coords.POP22_GRAPHICS.get(mode)
                if raw_coords:
                    src = COORD_SOURCE.get(os_id, (1920, 1080))
                    coords = adjust_coords(raw_coords, src)
                    self.driver.click_at(coords)
            if self.artifacts and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"set graphics {mode}\n", step="set")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary=f"graphics {mode}", data={"graphics": mode})
        except Exception as exc:
            return WorkflowResult(success=False, item_id=item_id, summary=str(exc))


    def get_transition_order(self, item_id: str = "gui.graphics_transitions") -> list[tuple[str, str]]:
        """Determine chained transition order (same as CLI)."""
        handler = System76Power(
            test_id="system76_power.gui.graphics",
            item_id=item_id,
            phase="verify",
            artifacts=self.artifacts,
        )
        switchable = System76Power.load_switchable_state()
        if switchable is None:
            switchable = handler.switchable()
            System76Power.save_switchable_state(switchable)
        if switchable != "switchable":
            return []

        modes = list(handler.graphics_modes)
        current = handler.get_graphics_mode()
        if current not in modes:
            current = modes[0] if modes else None
        if current is None:
            return []

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
        path = [(s, t) for s, t in chained_order if s in modes and t in modes]

        if current != "integrated" and "integrated" in modes and current in modes:
            forced = (current, "integrated")
            if forced not in path:
                path = [forced] + path

        return path

    def transition_to_integrated(self, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transition.to_integrated") -> WorkflowResult:
        """Transition from current mode to integrated via GUI clicks."""
        if not os_id.startswith("pop-22"):
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

        handler = System76Power(
            test_id="system76_power.gui.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        switchable = System76Power.load_switchable_state()
        if switchable is None:
            switchable = handler.switchable()
            System76Power.save_switchable_state(switchable)
        if switchable != "switchable":
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not switchable", data={"skipped": True})

        current = handler.get_graphics_mode()
        if current == "integrated":
            return WorkflowResult(success=True, item_id=item_id, summary="already integrated", data={"from": current, "to": "integrated", "actual": current, "verified": True})

        # Switch to integrated via GUI
        self.set_graphics_mode_gui("integrated", os_id=os_id, item_id=item_id)
        import time
        time.sleep(90)
        self.dismiss_menus()
        handler.setup_autologin()
        handler.reboot()
        handler.wait_for_boot()
        current = handler.get_graphics_mode()
        verified = (current == "integrated")
        return WorkflowResult(success=verified, item_id=item_id, summary=f"to_integrated (actual: {current}, verified={verified})", data={"from": current, "to": "integrated", "actual": current, "verified": verified})

    def transition_graphics(self, source: str, target: str, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transitions") -> WorkflowResult:
        """Execute a single graphics mode transition via GUI clicks.

        Mirrors the CLI transition_graphics phase machine so it survives reboots.
        """
        if not os_id.startswith("pop-22"):
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

        handler = System76Power(
            test_id="system76_power.gui.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        switchable = System76Power.load_switchable_state()
        if switchable is None:
            switchable = handler.switchable()
            System76Power.save_switchable_state(switchable)
        if switchable != "switchable":
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
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
        print(f"  [GUI] transition {source}->{target}: current mode = {current!r}", flush=True)

        # If already in target mode, verify and return without rebooting.
        if current == target:
            print(f"  [GUI] Already in {target} mode, no transition needed.", flush=True)
            verified = True
            gui_verified = None
            # GUI verification (only on 22.04).
            try:
                det = self.detect_graphics_mode(os_id=os_id)
                if det.success:
                    detected = (det.data or {}).get("graphics", "").lower()
                    gui_verified = (detected == target.lower())
                    if gui_verified is not None:
                        verified = verified and gui_verified
            except Exception:
                gui_verified = None
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
                    self.artifacts.save_text(item_id, "action", "transition -> " + source + " to " + target + " (verified=" + str(verified) + ")\n", step="transition")
                except Exception:
                    pass
            return WorkflowResult(
                success=verified,
                item_id=item_id,
                summary=f"{source}->{target} (actual: {current}, verified={verified})",
                data={"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified},
            )

        # --- Phase: start - switch to target via GUI, save, reboot ---
        if phase == "start":
            self.set_graphics_mode_gui(target, os_id=os_id, item_id=item_id)
            import time
            time.sleep(5)
            self.dismiss_menus()
            self.persist_state(item_id, "state", {
                "kind": "graphics_transition",
                "phase": "rebooting",
                "source": source,
                "target": target,
                "current": target,
                "results": results,
            })
            handler.setup_autologin()
            handler.reboot()
            handler.wait_for_boot()
            current = handler.get_graphics_mode()
            phase = "rebooting"
            print(f"  [GUI] after reboot: mode = {current!r} (target={target!r})", flush=True)

        # --- Phase: rebooting — verify target, record result ---
        if phase in ("rebooting", "done"):
            current = handler.get_graphics_mode()
            print(f"  [GUI] verify: current={current!r} target={target!r} match={current == target}", flush=True)
            target_ok = (current == target)

            # GUI verification (only on 22.04).
            gui_verified = None
            try:
                det = self.detect_graphics_mode(os_id=os_id)
                if det.success:
                    detected = (det.data or {}).get("graphics", "").lower()
                    gui_verified = (detected == target.lower())
                else:
                    gui_verified = False
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
                    self.artifacts.save_text(item_id, "action", "transition -> " + source + " to " + target + " (verified=" + str(verified) + ")\n", step="transition")
                except Exception:
                    pass

            return WorkflowResult(
                success=verified,
                item_id=item_id,
                summary=f"{source}->{target} (actual: {current}, verified={verified})",
                data={"from": source, "to": target, "actual": current, "verified": verified, "gui_verified": gui_verified},
            )

        # Fallback
        return WorkflowResult(success=False, item_id=item_id, summary=f"{source}->{target} (unexpected phase: {phase})")

    def transition_graphics_all(self, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transitions") -> WorkflowResult:
        """Run all graphics transitions via GUI in the order determined by starting mode."""
        if not os_id.startswith("pop-22"):
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

        handler = System76Power(
            test_id="system76_power.gui.graphics",
            item_id=item_id,
            phase="action",
            artifacts=self.artifacts,
        )
        switchable = System76Power.load_switchable_state()
        if switchable is None:
            switchable = handler.switchable()
            System76Power.save_switchable_state(switchable)
        if switchable != "switchable":
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="skipped")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary="not switchable", data={"skipped": True})

        # First, ensure we start in integrated mode.
        to_int = self.transition_to_integrated(os_id=os_id, item_id=f"{item_id}.to_integrated")

        order = self.get_transition_order(item_id=item_id)
        results = []
        all_ok = True
        for source, target in order:
            res = self.transition_graphics(source, target, os_id=os_id, item_id=f"{item_id}.{source}_to_{target}")
            entry = res.data if res.data else {"from": source, "to": target, "actual": None, "verified": res.success}
            results.append(entry)
            if not res.success:
                all_ok = False

        final_report = "\n".join(
            f"{e['from']}->{e['to']} (actual: {e.get('actual')}, verified={e.get('verified', '?')})"
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

    def detect_power_profile(
        self,
        os_id: str,
        item_id: str = "gui.power_profile_detect",
    ) -> WorkflowResult:
        """Detect current power profile via UI.

        Ubuntu uses 'Power Saver' label; Pop!_OS uses 'High Performance',
        'Balanced', 'Battery Saver' or 'Battery'.
        """
        if os_id == "ubuntu-26.04":
            expected = {"performance", "balanced", "battery"}
            prompt = (
                "Look at this screenshot of Ubuntu power settings. "
                "What power mode is currently active? "
                "The GUI may show 'Performance', 'Balanced', or 'Power Saver'. "
                "'Power Saver' means 'battery'. "
                "Return ONLY the CLI name: 'performance', 'balanced', or 'battery'."
            )
        else:
            expected = {"performance", "balanced", "battery"}
            prompt = (
                "Look at this screenshot of the power settings. "
                "What power profile is currently active? "
                "The GUI may show 'High Performance' (means 'performance'), "
                "'Balanced', 'Battery', or 'Battery Saver' (means 'battery'). "
                "Return ONLY the CLI name: 'performance', 'balanced', or 'battery'."
            )

        # Dismiss any open panels first by clicking center.
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        import time
        time.sleep(1)
        try:
            self.open_power_settings(os_id)
        except Exception:
            pass
        time.sleep(8)
        # Try detection up to 2 times.
        value = None
        result = None
        for attempt in range(2):
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
            # Click center to dismiss screenshot notification, then wait.
            try:
                self.driver.go_to((0.5, 0.5))
                self.driver.click_at((0.5, 0.5))
            except Exception:
                pass
            import time as _t
            _t.sleep(5)
            # If detected value matches a known profile, accept it.
            if value and value.lower() in {e.lower() for e in expected}:
                break
            # Otherwise retry after re-opening settings.
            if attempt == 0:
                try:
                    self.open_power_settings(os_id)
                except Exception:
                    pass
                import time as _t2
                _t2.sleep(3)

        if self.artifacts is not None and item_id:
            try:
                ok = value.lower() in {e.lower() for e in expected}
                self.artifacts.record_item(item_id, status="passed" if ok else "failed")
            except Exception:
                pass

        # Normalize: map GUI labels to CLI names.
        normalized = value.lower().strip()
        if normalized in ("high performance", "high-performance"):
            normalized = "performance"
        elif normalized in ("battery saver", "battery-saver", "power saver", "power-saver"):
            normalized = "battery"

        return WorkflowResult(
            success=value.lower() in {e.lower() for e in expected},
            item_id=item_id,
            summary=f"profile={value}",
            data={"profile": normalized, "raw": value, "normalized": result.normalized},
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

        # Click center to dismiss screenshot notification, then wait.
        try:
            self.driver.go_to((0.5, 0.5))
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        import time as _t
        _t.sleep(5)

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

    def ensure_max_brightness(self, item_id: str = "brightness.setup") -> WorkflowResult:
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

    def set_brightness_max(self, item_id: str = "brightness.max") -> WorkflowResult:
        return self.ensure_max_brightness(item_id=item_id)

    def set_brightness_min(self, item_id: str = "brightness.min") -> WorkflowResult:
        ok = self.brightness.brightness_down_to_min()
        b = self.brightness.current()
        m = self.brightness.maximum()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "setup", f"brightness={b}/{m}\n", step="min_brightness")
            except Exception:
                pass
        return WorkflowResult(success=ok, item_id=item_id, summary=f"brightness={b}/{m}", data={"brightness": b, "max": m})

    def get_brightness(self, item_id: str = "brightness.get") -> WorkflowResult:
        b = self.brightness.current()
        m = self.brightness.maximum()
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(item_id, "verify", f"brightness={b}/{m}\n", step="brightness")
            except Exception:
                pass
        return WorkflowResult(success=b is not None, item_id=item_id, summary=f"{b}/{m}", data={"brightness": b, "max": m})




