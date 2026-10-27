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
