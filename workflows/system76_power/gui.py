from __future__ import annotations

from harness.brightness import BrightnessHandler
from handlers.system76_power import System76Power

from harness.gui import GuiDriver
from harness.gui.coords import adjust_coords
from harness.workflows.base import Workflow, WorkflowResult

from .graphics_transitions import GraphicsTransitionMixin


def _reboot_and_wait(handler, graceful: bool = False) -> bool:
    """Reboot and wait (kept as a module-level name for test patchability)."""
    from .util import reboot_and_wait

    return reboot_and_wait(handler, graceful=graceful)


class System76PowerGUIWorkflow(Workflow, GraphicsTransitionMixin):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.driver = GuiDriver(artifacts=artifacts)
        self.brightness = BrightnessHandler()
        # Flavor used by the transition hooks; set by the transition entry
        # points, defaulted so the mixin works even if a hook runs first.
        from harness.platform import detect_platform

        try:
            self._os_id = detect_platform().os_id
        except Exception:
            self._os_id = "pop-22.04"

    def open_power_settings(self, os_id: str | None) -> WorkflowResult:
        """Open the power settings panel using the platform flavor's click layout."""
        import sys
        import time
        from harness.gui.coords import get_display_resolution
        from harness.platform import detect_platform, get_flavor_for_os_id

        if not os_id:
            os_id = detect_platform().os_id
        flavor = get_flavor_for_os_id(os_id)
        src = flavor.get_coord_source()
        dst = get_display_resolution()
        click_delay = flavor.get_click_delay()
        try:
            print(
                f"[open_power_settings] os_id={os_id} flavor={flavor.name} src={src} dst={dst}",
                file=sys.stderr,
                flush=True,
            )
            # Start from a known state: a click on the desktop dismisses any
            # menu/panel left open by a previous attempt, so clicking the
            # indicator below always *opens* it instead of toggling it closed.
            try:
                self.driver.click_at((0.5, 0.5))
                time.sleep(1)
            except Exception:
                pass
            flavor.pre_open_hook(self.driver)
            for click in flavor.get_open_clicks():
                coords = adjust_coords(click, src, dst)
                print(f"[open_power_settings] clicking {coords}", file=sys.stderr, flush=True)
                self.driver.click_at(coords)
                time.sleep(click_delay)
            for click in flavor.get_extra_clicks():
                coords = adjust_coords(click, src, dst)
                print(f"[open_power_settings] clicking extra {coords}", file=sys.stderr, flush=True)
                self.driver.click_at(coords)
                time.sleep(click_delay)
            flavor.post_click_hook(self.driver)
            time.sleep(flavor.get_wait_after_clicks())
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
        time.sleep(5)
        handler = System76Power(artifacts=self.artifacts)
        actual = handler.get_perf_profile()
        print(f"[transition_perf_profile] CLI profile after: {actual} (target={target})", file=sys.stderr, flush=True)
        verified = (actual == target)
        # Also verify via GUI detection using UI workflow
        gui_verified = None
        try:
            from harness.workflows.ui_workflow import UIWorkflow
            from harness.gui.coords import adjust_coords, get_display_resolution
            from harness.platform import get_flavor_for_os_id

            flavor = get_flavor_for_os_id(os_id)
            src_c = flavor.get_coord_source()
            dst_c = get_display_resolution()
            clicks = [
                adjust_coords(click, src_c, dst_c)
                for click in flavor.get_open_clicks()
            ]
            clicks.extend(
                adjust_coords(click, src_c, dst_c)
                for click in flavor.get_extra_clicks()
            )
            ui = UIWorkflow(artifacts=self.artifacts)
            det = ui.detect_from_ui(
                clicks=clicks,
                prompt=flavor.get_profile_prompt(),
                expected=flavor.get_profile_expected(),
                os_id=os_id,
                delay_between_clicks=flavor.get_click_delay(),
                wait_after_clicks=flavor.get_wait_after_clicks(),
                item_id=f"{item_id}.detect",
                max_attempts=5,
            )
            if det.success:
                detected = flavor.normalize_profile((det.data or {}).get("value", ""))
                gui_verified = (detected == target.lower())
        except Exception as e:
            print(f"[transition_perf_profile] gui verify failed: {e}", file=sys.stderr, flush=True)
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
            from harness.platform import get_flavor_for_os_id
            from harness.gui.coords import get_display_resolution
            flavor = get_flavor_for_os_id(os_id)
            src = flavor.get_coord_source()
            dst = get_display_resolution()
            raw_coords = flavor.get_profile_coords(profile)
            coords = adjust_coords(raw_coords, src, dst) if raw_coords else None
            print(f"[set_power_profile_gui] profile={profile} raw={raw_coords} src={src} dst={dst} adjusted={coords}", file=sys.stderr, flush=True)
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
            import sys
            from harness.platform import get_flavor_for_os_id
            from harness.gui.coords import get_display_resolution
            self.open_power_settings(os_id)
            flavor = get_flavor_for_os_id(os_id)
            raw_coords = flavor.get_graphics_coords(mode)
            if raw_coords:
                src = flavor.get_coord_source()
                dst = get_display_resolution()
                coords = adjust_coords(raw_coords, src, dst)
                print(f"[set_graphics_mode_gui] mode={mode} raw={raw_coords} src={src} dst={dst} adjusted={coords}", file=sys.stderr, flush=True)
                self.driver.click_at(coords)
            if self.artifacts and item_id:
                try:
                    self.artifacts.save_text(item_id, "action", f"set graphics {mode}\n", step="set")
                except Exception:
                    pass
            return WorkflowResult(success=True, item_id=item_id, summary=f"graphics {mode}", data={"graphics": mode})
        except Exception as exc:
            return WorkflowResult(success=False, item_id=item_id, summary=str(exc))


    # --- GraphicsTransitionMixin hooks (GUI driver) -------------------------

    def _make_handler(self, item_id: str, phase: str):
        return System76Power(
            test_id="system76_power.gui.graphics",
            item_id=item_id,
            phase=phase,
            artifacts=self.artifacts,
        )

    def _transition_log_prefix(self) -> str:
        return "  [GUI] "

    def _switch_graphics_mode(self, handler, target: str) -> tuple[bool, str, str]:
        res = self.set_graphics_mode_gui(target, item_id=None)
        return bool(res.success), res.summary, res.summary

    def _gui_verify_transition(self, target: str, item_id: str) -> bool | None:
        """Visual check via the graphics panel; required evidence (None = no UI).

        Detection failures count as False — a detection error never proves
        the panel shows the target, so it must fail the transition rather
        than silently pass it (this matches the CLI driver's semantics).
        """
        from harness.platform import get_flavor_for_os_id

        if not get_flavor_for_os_id(self._os_id).supports_graphics_switching():
            return None
        det = self.detect_graphics_mode(os_id=self._os_id, target=target)
        if not det.success:
            return False
        detected = ((det.data or {}).get('graphics') or '').lower()
        return detected == target.lower()

    def _reboot_after_switch(self, handler, target: str) -> bool:
        """Pop!_OS 22.04: the shell's post-switch modal performs the reboot.

        Forcing a hard reboot right after the extension click lands while
        the mode switch is still in flight and has left machines in a broken
        state.  On this flavor the modal's "Reboot Now" button is activated
        with Tab, Tab, Enter after a 90 s settle (hardware-verified key
        sequence — no coordinates needed).  Flavors without the modal keep
        the scripted settle+reboot path.
        """
        from harness.platform import get_flavor_for_os_id

        if not get_flavor_for_os_id(self._os_id).supports_graphics_switching():
            return super()._reboot_after_switch(handler, target)
        from .util import popup_reboot_and_wait

        return popup_reboot_and_wait(handler)

    # --- mixin entry points (historical GUI signatures preserved) ------------

    def transition_to_hybrid(self, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transition.to_hybrid") -> WorkflowResult:
        self._os_id = os_id
        return self._transition_to_hybrid_core(item_id=item_id)

    def transition_graphics(self, source: str, target: str, os_id: str = "pop-22.04", item_id: str = "gui.graphics_transitions") -> WorkflowResult:
        self._os_id = os_id
        return self._transition_graphics_core(source, target, item_id=item_id)

    def detect_power_profile(
        self,
        os_id: str,
        item_id: str = "gui.power_profile_detect",
        target: str | None = None,
    ) -> WorkflowResult:
        """Detect current power profile via UI.

        Prompts and expected labels come from the platform flavor (for example
        Ubuntu says 'Power Saver' while Pop!_OS says 'Battery Saver').

        ``target``, when given, must be matched before detection is accepted;
        otherwise a recognized profile (even the wrong one) ends the loop.
        """
        from harness.platform import get_flavor_for_os_id

        flavor = get_flavor_for_os_id(os_id)
        expected = flavor.get_profile_expected()
        prompt = flavor.get_profile_prompt()

        # Dismiss any open panels first by clicking center (twice).
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        import time
        time.sleep(2)
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        time.sleep(3)
        # Open power settings fresh using the platform flavor's layout.
        try:
            self.open_power_settings(os_id)
        except Exception:
            pass
        time.sleep(12)

        def _normalize(raw: str) -> str:
            """Map LLM responses to the three CLI profile names.

            Prefer explicit conclusion, otherwise use the LAST mention.
            """
            import re

            n = (raw or "").lower().strip()
            if not n:
                return ""

            # Explicit conclusion statement wins.
            m = re.search(r"selected(?: performance)? profile is\s*[:*\"]?\s*(performance|balanced|battery)", n)
            if m:
                return m.group(1)

            # Map synonyms to canonical names.
            def _canonical(s: str) -> str:
                if s in ("high performance", "performance"):
                    return "performance"
                if s in ("power saver", "battery saver", "battery", "powersaver", "batterysaver"):
                    return "battery"
                if s == "balanced":
                    return "balanced"
                return s

            # Find all profile mentions.
            patterns = [
                r"high performance",
                r"performance",
                r"power saver",
                r"battery saver",
                r"batterysaver",
                r"powersaver",
                r"balanced",
                r"battery",
            ]
            matches = []
            for p in patterns:
                for m in re.finditer(p, n):
                    matches.append((_canonical(m.group(0)), m.start()))

            if not matches:
                return ""

            # Use the LAST occurrence - conclusion is usually at the end
            last_canon, _ = matches[-1]
            return last_canon

        # Try detection up to 5 times before failing.
        value = None
        result = None
        normalized = None
        for attempt in range(5):
            try:
                value, result = self.driver.capture_and_detect(
                    prompt,
                    expected,
                    item_id=item_id,
                    phase="detect",
                    step="power_profile",
                )
            except Exception as exc:
                print(f"  [detect_power_profile] attempt {attempt} failed: {exc}", flush=True)
                value, result = None, None
            # Click center to dismiss screenshot notification/menus, then wait.
            try:
                self.dismiss_menus()
            except Exception:
                try:
                    self.driver.go_to((0.5, 0.5))
                    self.driver.click_at((0.5, 0.5))
                    import time as _t
                    _t.sleep(1)
                    self.driver.click_at((0.5, 0.5))
                except Exception:
                    pass
            import time as _t
            _t.sleep(3)
            if value is not None:
                normalized = _normalize(value)
                recognized = normalized in ("performance", "balanced", "battery")
                match = normalized == target.lower() if target is not None else recognized
                print(
                    f"  [detect_power_profile] attempt={attempt} target={target} detected={normalized} match={match}",
                    flush=True,
                )
                if match:
                    break
            # Otherwise retry after re-opening settings.
            try:
                self.open_power_settings(os_id)
                import time as _t2b
                _t2b.sleep(8)
            except Exception:
                pass
            import time as _t2b
            _t2b.sleep(3)

        if self.artifacts is not None and item_id:
            try:
                verified = normalized is not None and (
                    target is None or normalized == target.lower()
                ) and normalized in ("performance", "balanced", "battery")
                self.artifacts.record_item(item_id, status="passed" if verified else "failed")
            except Exception:
                pass

        if normalized is None:
            return WorkflowResult(
                success=False, item_id=item_id, summary="detect failed after 5 attempts"
            )

        # Normalize: map GUI labels to CLI names (already done in _normalize).
        verified = normalized in ("performance", "balanced", "battery") and (
            target is None or normalized == target.lower()
        )

        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"profile={normalized}",
            data={"profile": normalized, "raw": value, "normalized": getattr(result, "normalized", None)},
        )

    def detect_power_profile_som(
        self,
        os_id: str,
        item_id: str = "gui.power_profile_detect_som",
        target: str | None = None,
    ) -> WorkflowResult:
        """Detect power profile using Set-of-Mark (OpenCV + Ollama ID matching).

        The driver retries up to 5 times (fresh screenshot + LLM each attempt);
        ``target`` must be matched before detection is accepted.
        """
        import time
        try:
            self.open_power_settings(os_id)
        except Exception:
            pass
        time.sleep(5)

        label = self.driver.detect_power_profile_som(os_id, item_id=item_id, phase="detect", step="som_profile", target=target)
        if label is None:
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.record_item(item_id, status="failed")
                except Exception:
                    pass
            return WorkflowResult(success=False, item_id=item_id, summary="SoM detection failed after 5 attempts")

        # Click center to dismiss notification.
        try:
            self.driver.click_at((0.5, 0.5))
        except Exception:
            pass
        time.sleep(5)

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.record_item(item_id, status="passed")
            except Exception:
                pass

        return WorkflowResult(
            success=True,
            item_id=item_id,
            summary=f"profile={label}",
            data={"profile": label},
        )

    def detect_graphics_mode(
        self,
        os_id: str | None = "pop-22.04",
        item_id: str = "gui.graphics_mode_detect",
        target: str | None = None,
    ) -> WorkflowResult:
        """Detect graphics mode via UI for the given OS.

        ``target``, when given, must be matched before detection is accepted;
        otherwise a recognized mode (even the wrong one) ends the loop.
        """
        from harness.platform import detect_platform, get_flavor_for_os_id

        if not os_id:
            os_id = detect_platform().os_id
        flavor = get_flavor_for_os_id(os_id)
        if not flavor.supports_graphics_switching():
            return WorkflowResult(success=True, item_id=item_id, summary="not applicable", data={"skipped": True})

        prompt = flavor.get_graphics_prompt()
        expected = flavor.get_graphics_expected()

        try:
            # Dismiss any open panels first by clicking center.
            try:
                self.driver.go_to((0.5, 0.5))
                self.driver.click_at((0.5, 0.5))
            except Exception:
                pass
            import time as _t0
            _t0.sleep(1)
            # Open power settings fresh.
            try:
                self.open_power_settings(os_id)
            except Exception:
                pass
            import time as _t1
            _t1.sleep(10)
            # Try detection up to 5 times before failing.
            value = None
            result = None
            for attempt in range(5):
                try:
                    value, result = self.driver.capture_and_detect(
                        prompt,
                        expected,
                        item_id=item_id,
                        phase="detect",
                        step="graphics_mode",
                    )
                except Exception as exc:
                    print(f"  [detect_graphics_mode] attempt {attempt} failed: {exc}", flush=True)
                    value, result = None, None
                # Click center to dismiss screenshot notification/menus, then wait.
                try:
                    self.dismiss_menus()
                except Exception:
                    try:
                        self.driver.go_to((0.5, 0.5))
                        self.driver.click_at((0.5, 0.5))
                        import time as _t
                        _t.sleep(1)
                        self.driver.click_at((0.5, 0.5))
                    except Exception:
                        pass
                import time as _t2
                _t2.sleep(3)
                # If detected value matches a known (or target) mode, accept it.
                if value:
                    match = value.lower() == target.lower() if target is not None else value.lower() in {e.lower() for e in expected}
                    print(
                        f"  [detect_graphics_mode] attempt={attempt} target={target} detected={value.lower()} match={match}",
                        flush=True,
                    )
                    if match:
                        break
                # Otherwise reopen settings before the next attempt.
                try:
                    self.open_power_settings(os_id)
                except Exception:
                    pass
                import time as _t3
                _t3.sleep(3)
        except Exception as exc:
            return WorkflowResult(
                success=False, item_id=item_id, summary=f"detect failed: {exc}"
            )

        if value is None:
            return WorkflowResult(
                success=False, item_id=item_id, summary="detect failed after 5 attempts"
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
                verified = value.lower() in expected and (
                    target is None or value.lower() == target.lower()
                )
                self.artifacts.record_item(item_id, status="passed" if verified else "failed")
            except Exception:
                pass

        verified = value.lower() in expected and (
            target is None or value.lower() == target.lower()
        )
        return WorkflowResult(
            success=verified,
            item_id=item_id,
            summary=f"graphics={value}",
            data={"graphics": value, "normalized": getattr(result, "normalized", None)},
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




