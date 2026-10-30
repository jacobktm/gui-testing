"""Unified UI interaction workflow.

Provides single workflows for:
- Opening UI elements (click sequence)
- Taking screenshots  
- Querying LLM
- Chaining them together
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .base import Workflow, WorkflowResult


class UIWorkflow(Workflow):
    """Single workflow for UI interactions, screenshots, and LLM queries."""

    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        from ..gui import GuiDriver
        self.driver = GuiDriver(artifacts=artifacts)

    def open_ui_elements(
        self,
        clicks: list[tuple[float, float]],
        delay_between: float = 2.0,
        item_id: str | None = None,
    ) -> WorkflowResult:
        """Click through a list of coordinates to open UI elements."""
        try:
            for i, coords in enumerate(clicks):
                self.driver.click_at(coords)
                if i < len(clicks) - 1:
                    time.sleep(delay_between)
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary=f"clicked {len(clicks)} elements",
                data={"clicks": clicks},
            )
        except Exception as e:
            return WorkflowResult(
                success=False,
                item_id=item_id,
                summary=f"failed to open UI: {e}",
                data={"error": str(e)},
            )

    def take_screenshot(
        self,
        os_id: str = None,
        item_id: str | None = None,
        out_dir: str = "/tmp/opencode/gui",
    ) -> WorkflowResult:
        """Take a screenshot using OS-appropriate method."""
        try:
            from ..screenshots import capture
            import os
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            import time
            ts = int(time.time() * 1000)
            shot_path = Path(out_dir) / f"screenshot_{ts}.png"
            screenshot = capture(shot_path)
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary=f"screenshot taken: {screenshot.path}",
                data={"path": str(screenshot.path), "width": screenshot.width, "height": screenshot.height},
            )
        except Exception as e:
            return WorkflowResult(
                success=False,
                item_id=item_id,
                summary=f"screenshot failed: {e}",
                data={"error": str(e)},
            )

    def query_llm(
        self,
        prompt: str,
        image_path: str,
        expected: set[str] | list[str] = None,
        item_id: str | None = None,
    ) -> WorkflowResult:
        """Query LLM with prompt and image."""
        try:
            from ..detection import parse_detection
            resp = self.driver.ollama.send_message(prompt, [image_path])
            if not resp:
                return WorkflowResult(
                    success=False,
                    item_id=item_id,
                    summary="empty response from LLM",
                )
            if expected:
                try:
                    result = parse_detection(resp, expected=expected)
                    return WorkflowResult(
                        success=True,
                        item_id=item_id,
                        summary=f"detected: {result.value}",
                        data={"value": result.value, "normalized": result.normalized, "response": resp},
                    )
                except Exception as e:
                    return WorkflowResult(
                        success=False,
                        item_id=item_id,
                        summary=f"parse failed: {e}",
                        data={"response": resp},
                    )
            return WorkflowResult(
                success=True,
                item_id=item_id,
                summary="got response",
                data={"response": resp},
            )
        except Exception as e:
            return WorkflowResult(
                success=False,
                item_id=item_id,
                summary=f"llm query failed: {e}",
                data={"error": str(e)},
            )

    def detect_from_ui(
        self,
        clicks: list[tuple[float, float]],
        prompt: str,
        expected: set[str] | list[str],
        os_id: str = None,
        delay_between_clicks: float = 2.0,
        wait_after_clicks: float = 5.0,
        item_id: str = None,
        max_attempts: int = 5,
    ) -> WorkflowResult:
        """Chain: click UI elements -> take screenshot -> query LLM."""
        from ..screenshots import capture, crop_active_display
        from ..detection import parse_detection, DetectionParseError
        from pathlib import Path
        import time
        import os

        out_dir = Path("/tmp/opencode/gui")
        out_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_attempts):
            # Open UI elements
            res = self.open_ui_elements(clicks, delay_between_clicks, item_id=f"{item_id}.open_{attempt}")
            if not res.success:
                time.sleep(2)
                continue

            time.sleep(wait_after_clicks)

            # Take screenshot
            ts = int(time.time() * 1000)
            shot_path = out_dir / f"detect_{attempt}_{ts}.png"
            try:
                screenshot = capture(shot_path)
                crop_path = out_dir / f"active_{attempt}_{ts}.png"
                crop = crop_active_display(screenshot, crop_path)
            except Exception as e:
                print(f"[detect_from_ui] attempt {attempt} screenshot failed: {e}")
                # Dismiss and retry
                try:
                    self.driver.click_at((0.5, 0.5))
                except Exception:
                    pass
                time.sleep(3)
                continue

            # Query LLM
            try:
                resp = self.driver.ollama.send_message(prompt, [str(crop.path)])
                if not resp or not resp.strip():
                    print(f"[detect_from_ui] attempt {attempt} empty response")
                    try:
                        self.driver.click_at((0.5, 0.5))
                    except Exception:
                        pass
                    time.sleep(2)
                    continue
                result = parse_detection(resp, expected=expected)
                # Dismiss
                try:
                    self.driver.click_at((0.5, 0.5))
                except Exception:
                    pass
                time.sleep(2)
                return WorkflowResult(
                    success=True,
                    item_id=item_id,
                    summary=f"detected: {result.value}",
                    data={"value": result.value, "normalized": result.normalized, "response": resp},
                )
            except DetectionParseError as e:
                print(f"[detect_from_ui] attempt {attempt} parse failed: {e}")
                try:
                    self.driver.click_at((0.5, 0.5))
                except Exception:
                    pass
                time.sleep(3)
                continue
            except Exception as e:
                print(f"[detect_from_ui] attempt {attempt} llm failed: {e}")
                try:
                    self.driver.click_at((0.5, 0.5))
                except Exception:
                    pass
                time.sleep(3)
                continue

        return WorkflowResult(success=False, item_id=item_id, summary=f"failed after {max_attempts} attempts")
