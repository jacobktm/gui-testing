from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..detection import parse_detection, to_dotool_normalized
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

    def detect_coordinates(
        self,
        label: str,
        *,
        reference: tuple[float, float] | None = None,
        item_id: str | None = None,
        phase: str = "detect",
        step: str = "coordinates",
        out_dir: Path | str | None = None,
    ) -> tuple[float, float] | None:
        """Use Ollama to find normalized (x, y) coordinates of a UI element.

        Returns (x, y) in 0-1 range, or None if detection fails.
        """
        out_dir = Path(out_dir) if out_dir is not None else Path("/tmp/opencode/gui")
        out_dir.mkdir(parents=True, exist_ok=True)

        shot_path = out_dir / f"screenshot_{phase}.png"
        screenshot = capture(shot_path)

        active_path = out_dir / f"active_{phase}.png"
        crop = crop_active_display(screenshot, active_path)

        # Wait for screenshot notification to disappear.
        import time as _t
        _t.sleep(15)

        if reference is not None:
            ref_hint = f"The approximate position is ({reference[0]:.4f}, {reference[1]:.4f}). Adjust if needed for this display. "
        else:
            ref_hint = ""
        prompt = (
            f"Look at this screenshot of system settings. "
            f"Find the button or menu item labeled '{label}'. "
            f"{ref_hint}"
            f"Return ONLY its center position as two numbers between 0.0 and 1.0. "
            f"Use at least 4 decimal places of precision. "
            f"Format: x,y (for example: 0.9550,0.2400). "
            f"Do not include any other text or explanation."
        )

        response = None
        try:
            if self.ollama.client and self.ollama.model:
                response = self.ollama.send_message(prompt, [str(crop.path)])
        except Exception:
            response = None

        if response is None:
            return None

        # Parse "x,y" from response.
        import re
        match = re.search(r'(\d+\.?\d*)\s*[,\s]\s*(\d+\.?\d*)', response)
        if match:
            try:
                x = float(match.group(1))
                y = float(match.group(2))
                if 0 <= x <= 1 and 0 <= y <= 1:
                    if self.artifacts is not None and item_id:
                        try:
                            self.artifacts.save_text(
                                item_id, phase,
                                f"label={label} coords=({x},{y}) response={response}\n",
                                step=step,
                            )
                        except Exception:
                            pass
                    return (x, y)
            except ValueError:
                pass
        return None

    def detect_all_coordinates(
        self,
        labels: list[str],
        *,
        references: dict[str, tuple[float, float]] | None = None,
        item_id: str | None = None,
        phase: str = "detect",
        step: str = "all_coords",
        out_dir: Path | str | None = None,
    ) -> dict[str, tuple[float, float]]:
        """Use Ollama to find normalized coordinates for multiple UI elements at once.

        Returns a dict mapping label -> (x, y). Missing labels are omitted.
        """
        out_dir = Path(out_dir) if out_dir is not None else Path("/tmp/opencode/gui")
        out_dir.mkdir(parents=True, exist_ok=True)

        shot_path = out_dir / f"screenshot_{phase}.png"
        screenshot = capture(shot_path)

        active_path = out_dir / f"active_{phase}.png"
        crop = crop_active_display(screenshot, active_path)

        # Wait for screenshot notification to disappear.
        import time as _t
        _t.sleep(15)

        label_list = ", ".join(f"'{l}'" for l in labels)
        ref_hint = ""
        if references:
            ref_lines = []
            for l in labels:
                if l in references:
                    ref_lines.append(f"  {l}: approx ({references[l][0]:.4f}, {references[l][1]:.4f})")
            if ref_lines:
                ref_hint = "Approximate positions (adjust for this display):\n" + "\n".join(ref_lines) + "\n"
        prompt = (
            f"Look at this screenshot of system settings. "
            f"For each of these UI elements: {label_list}, "
            f"return their center coordinates as normalized values (0.0 to 1.0). "
            f"{ref_hint}"
            f"Format: label=x,y on separate lines. "
            f"Example:\nHigh Performance=0.9550,0.2400\nBalanced=0.9550,0.1800\n"
            f"Only return coordinates, nothing else."
        )

        response = None
        try:
            if self.ollama.client and self.ollama.model:
                response = self.ollama.send_message(prompt, [str(crop.path)])
        except Exception:
            response = None

        result = {}
        if response:
            import re
            for line in response.strip().splitlines():
                # Match "label=x,y" or "label: x, y" or "label x y"
                m = re.match(r"(.+?)\s*[=:]\s*(\d+\.?\d*)\s*[,\s]\s*(\d+\.?\d*)", line.strip())
                if m:
                    label = m.group(1).strip().strip(chr(39) + chr(34))
                    try:
                        x = float(m.group(2))
                        y = float(m.group(3))
                        if 0 <= x <= 1 and 0 <= y <= 1:
                            result[label] = (x, y)
                    except ValueError:
                        pass

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(
                    item_id, phase,
                    f"labels={labels}\ncoords={result}\nresponse={response}\n",
                    step=step,
                )
            except Exception:
                pass

        import sys
        print(f"[detect_all_coordinates] {result}", file=sys.stderr, flush=True)
        return result

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

        shot_path = out_dir / f"screenshot_{phase}.png"
        screenshot = capture(shot_path)

        active_path = out_dir / f"active_{phase}.png"
        crop = crop_active_display(
            screenshot,
            active_path,
            active_index=active_index,
        )

        # Send active display to model
        response = None
        try:
            if self.ollama.client and self.ollama.model:
                response = self.ollama.send_message(prompt, [str(crop.path)])
        except Exception:
            response = None

        result = parse_detection(response, expected=expected)

        # Wait for screenshot notification to disappear (15s).
        import time as _t
        _t.sleep(15)

        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_screenshot(
                    item_id, phase, screenshot.path, step=f"{step}_full"
                )
                self.artifacts.save_screenshot(
                    item_id, phase, crop.path, step=f"{step}_active"
                )
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
            except Exception:
                pass

        return result.value, result
