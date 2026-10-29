from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..detection import parse_detection, to_dotool_normalized
from .set_of_mark import generate_set_of_mark
from .set_of_mark import detect_element_coords
from ..dotool import click, mouseto
from ..ollama_client import Ollama
from ..screenshots import capture, crop_active_display


__all__ = ["GuiDriver"]


class GuiDriver:
    def __init__(self, artifacts=None, dtproc=None):
        self.artifacts = artifacts
        self.dtproc = dtproc
        self.ollama = Ollama()
        try:
            self.ollama.connect()
        except Exception:
            pass

    def go_to(self, coords: tuple[float, float], dtproc=None):
        proc = dtproc if dtproc is not None else self.dtproc
        mouseto(to_dotool_normalized(coords), dtproc=proc)
        return self

    def click_at(self, coords: tuple[float, float], dtproc=None):
        proc = dtproc if dtproc is not None else self.dtproc
        self.go_to(coords, dtproc=proc)
        click(dtproc=proc)
        return self

    def detect_coords_som(
        self,
        target_description: str,
        *,
        item_id: str | None = None,
        phase: str = "detect",
        step: str = "som_coords",
        out_dir: str | None = None,
    ) -> tuple[float, float] | None:
        """Use Set-of-Mark to find normalized coordinates of a UI element.

        Detects UI elements via OpenCV, annotates with IDs, asks Ollama
        which ID matches the target, returns normalized (x, y).
        """
        out_dir = out_dir or "/tmp/opencode/gui"
        os.makedirs(out_dir, exist_ok=True)
        import sys
        import time as _t
        from ..screenshots.screenshot import capture
        from ..screenshots.screenshot import crop_active_display

        # Try detection up to 5 times before failing; every attempt takes a
        # fresh screenshot and sends it to the model (never re-sends old data).
        coords = None
        for attempt in range(5):
            shot_path = os.path.join(out_dir, f"screenshot_{phase}_a{attempt}.png")
            try:
                screenshot = capture(shot_path)
            except Exception as e:
                print(f"[detect_coords_som] attempt {attempt} capture FAILED: {e}", file=sys.stderr, flush=True)
                screenshot = None
            crop = None
            if screenshot is not None:
                active_path = os.path.join(out_dir, f"active_{phase}_a{attempt}.png")
                try:
                    crop = crop_active_display(screenshot, active_path)
                except Exception as e:
                    print(f"[detect_coords_som] attempt {attempt} crop FAILED: {e}", file=sys.stderr, flush=True)

            _t.sleep(5)  # Wait for screenshot notification.

            if crop is not None:
                from ..config import ollama_config
                cfg = ollama_config()
                coords = detect_element_coords(
                    str(crop.path),
                    target_description,
                    ollama_ip=cfg.get("REMOTE_OLLAMA_IP", "127.0.0.1"),
                    ollama_port=cfg.get("REMOTE_OLLAMA_PORT", "11434"),
                    ollama_model=cfg.get("model", "qwen3-vl:8b"),
                )
                if coords is not None:
                    if self.artifacts is not None and item_id:
                        try:
                            self.artifacts.save_text(
                                item_id, phase,
                                f"target={target_description} coords={coords}\nattempt={attempt}\n",
                                step=step,
                            )
                        except Exception:
                            pass
                    print(f"[detect_coords_som] attempt={attempt} {target_description} -> {coords}", file=sys.stderr, flush=True)
                    return coords
            print(f"[detect_coords_som] attempt={attempt} no coords, retrying...", file=sys.stderr, flush=True)
            # Dismiss any screenshot notification before the next attempt.
            try:
                self.click_at((0.5, 0.5))
            except Exception:
                pass
            _t.sleep(2)
        print(f"[detect_coords_som] detected no coords after 5 attempts", file=sys.stderr, flush=True)
        return coords

    def detect_power_profile_som(
        self,
        os_id: str = "pop-24.04",
        *,
        item_id: str | None = None,
        phase: str = "detect",
        step: str = "som_profile",
        out_dir: str | None = None,
        target: str | None = None,
    ) -> str | None:
        """Use Set-of-Mark to detect the active power profile.

        Detects UI elements via OpenCV, annotates with IDs, asks Ollama
        which ID is currently selected/highlighted and what its label is.
        Returns the normalized profile name or None.

        ``target``, when given, must be matched before detection is accepted;
        otherwise a recognized profile (even the wrong one) ends the loop.
        """
        out_dir = out_dir or "/tmp/opencode/gui"
        os.makedirs(out_dir, exist_ok=True)
        import sys
        import time as _t
        from ..screenshots.screenshot import capture
        from ..screenshots.screenshot import crop_active_display

        # Try detection up to 5 times before failing; every attempt takes a
        # fresh screenshot and sends it to the model (never re-sends old data).
        for attempt in range(5):
            shot_path = os.path.join(out_dir, f"screenshot_{phase}_a{attempt}.png")
            try:
                screenshot = capture(shot_path)
            except Exception as e:
                print(f"[detect_power_profile_som] attempt {attempt} capture FAILED: {e}", file=sys.stderr, flush=True)
                screenshot = None
            crop = None
            if screenshot is not None:
                active_path = os.path.join(out_dir, f"active_{phase}_a{attempt}.png")
                try:
                    crop = crop_active_display(screenshot, active_path)
                except Exception as e:
                    print(f"[detect_power_profile_som] attempt {attempt} crop FAILED: {e}", file=sys.stderr, flush=True)

            _t.sleep(5)  # Wait for notification
            if crop is None:
                continue

            som_path, element_map = generate_set_of_mark(str(crop.path))
            if not element_map:
                print(f"[detect_power_profile_som] attempt={attempt} no UI elements detected, retrying...", file=sys.stderr, flush=True)
                continue

            # Ask Ollama which ID is selected and what its label is.
            prompt = "This screenshot has green numbered boxes around UI elements. One power profile option is currently selected or highlighted (it may have a checkmark, different color, or bold text). Which number is next to the selected profile? Also tell me the label of that element. Format: number,label (e.g., 5,Balanced). Return ONLY that."

            response = None
            try:
                if self.ollama.client and self.ollama.model:
                    response = self.ollama.send_message(prompt, [som_path])
            except Exception:
                response = None

            if response is None:
                print(f"[detect_power_profile_som] attempt={attempt} LLM unavailable, retrying...", file=sys.stderr, flush=True)
                continue

            label = self._parse_som_profile_response(response, element_map, item_id, phase, step, attempt)
            if label is None:
                print(f"[detect_power_profile_som] attempt={attempt} unparsable response, retrying...", file=sys.stderr, flush=True)
                continue
            print(
                f"[detect_power_profile_som] attempt={attempt} target={target} detected={label}",
                file=sys.stderr, flush=True,
            )
            if target is None or label == target.lower():
                return label
            # Mismatch — dismiss notification before next attempt.
            try:
                self.click_at((0.5, 0.5))
            except Exception:
                pass
            _t.sleep(2)
        print("[detect_power_profile_som] detection failed after 5 attempts", file=sys.stderr, flush=True)
        return None

    def _parse_som_profile_response(self, response: str, element_map: dict, item_id, phase, step, attempt):
        """Parse 'number,label' from a SoM response; returns normalized label or None."""
        import re

        # Parse "number,label" from response.
        match = re.search(r"(\d+)\s*[,\s]\s*(.+)", response.strip())
        if match:
            elem_id = int(match.group(1))
            label = match.group(2).strip().lower()
            # Normalize label.
            if "high performance" in label or label == "performance":
                label = "performance"
            elif "battery" in label:
                label = "battery"
            elif "balanced" in label:
                label = "balanced"
            if self.artifacts is not None and item_id:
                try:
                    self.artifacts.save_text(
                        item_id, phase,
                        f"som_id={elem_id} label={label} raw={response}\ncoords={element_map.get(elem_id)}\n",
                        step=step,
                    )
                except Exception:
                    pass
            import sys
            print(f"[detect_power_profile_som] id={elem_id} label={label}", file=sys.stderr, flush=True)
            return label

        # Fallback: just extract a number.
        match = re.search(r"\d+", response)
        if match:
            elem_id = int(match.group(0))
            if elem_id in element_map:
                # Can't determine label from ID alone.
                import sys
                print(f"[detect_power_profile_som] id={elem_id} (no label)", file=sys.stderr, flush=True)
                return None
        return None

    def capture_and_detect(
        self,
        prompt: str,
        expected: set[str] | list[str],
        *,
        item_id: str | None = None,
        phase: str = "verify",
        step: str = "detect",
        out_dir: Path | str | None = None,
        active_index: int | None = None,
    ) -> tuple[str, Any]:
        out_dir = Path(out_dir) if out_dir is not None else Path("/tmp/opencode/gui")
        out_dir.mkdir(parents=True, exist_ok=True)

        import time as _t
        _ts = int(_t.time() * 1000)
        shot_path = out_dir / f"screenshot_{phase}_{_ts}.png"
        import sys
        print(f"[capture_and_detect] capturing to {shot_path}", file=sys.stderr, flush=True)
        try:
            screenshot = capture(shot_path)
            print(f"[capture_and_detect] capture OK: {screenshot.path} {screenshot.width}x{screenshot.height}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[capture_and_detect] capture FAILED: {e}", file=sys.stderr, flush=True)
            raise

        active_path = out_dir / f"active_{phase}_{_ts}.png"
        try:
            crop = crop_active_display(
                screenshot,
                active_path,
                active_index=active_index,
            )
            print(f"[capture_and_detect] crop OK: {crop.path}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[capture_and_detect] crop FAILED: {e}", file=sys.stderr, flush=True)
            raise

        # Send active display to model
        response = None
        print(f"[capture_and_detect] calling LLM with model={self.ollama.model}", file=sys.stderr, flush=True)
        try:
            if self.ollama.client and self.ollama.model:
                response = self.ollama.send_message(prompt, [str(crop.path)])
                print(f"[capture_and_detect] LLM response: {response}", file=sys.stderr, flush=True)
            else:
                print(f"[capture_and_detect] Ollama not connected: client={self.ollama.client} model={self.ollama.model}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[capture_and_detect] LLM FAILED: {e}", file=sys.stderr, flush=True)
            response = None

        result = parse_detection(response, expected=expected)

        # Click center to dismiss screenshot notification, then wait.
        try:
            go_to = self.go_to
            click_at = self.click_at
            go_to((0.5, 0.5))
            click_at((0.5, 0.5))
        except Exception:
            pass
        import time as _t
        _t.sleep(5)

        if self.artifacts is not None and item_id:
            try:
                art = self.artifacts.save_screenshot(
                    item_id, phase, screenshot.path, step=f"{step}_full"
                )
                import sys
                print(f"[capture_and_detect] saved full screenshot: {art.path}", file=sys.stderr, flush=True)
            except Exception as e:
                import sys
                print(f"[capture_and_detect] save_screenshot full FAILED: {e}", file=sys.stderr, flush=True)
            try:
                art = self.artifacts.save_screenshot(
                    item_id, phase, crop.path, step=f"{step}_active"
                )
                import sys
                print(f"[capture_and_detect] saved active screenshot: {art.path}", file=sys.stderr, flush=True)
            except Exception as e:
                import sys
                print(f"[capture_and_detect] save_screenshot active FAILED: {e}", file=sys.stderr, flush=True)
            try:
                self.artifacts.save_detection(
                    item_id,
                    phase,
                    {
                        "value": result.value,
                        "normalized": result.normalized,
                        "prompt": prompt,
                        "response": response,
                    },
                    step=step,
                )
            except Exception as e:
                import sys
                print(f"[capture_and_detect] save_detection failed: {e}", file=sys.stderr, flush=True)

        return result.value, result
