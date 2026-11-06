"""Unified UI interaction workflow.

Provides single workflows for:
- Opening UI elements (click sequence)
- Taking screenshots  
- Querying LLM
- Chaining them together
"""

from __future__ import annotations

import time

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
        pre_open=None,
    ) -> WorkflowResult:
        """Click through a list of coordinates to open UI elements.

        ``pre_open``: optional caller-supplied callable run before the click
        sequence — apps use it to clear lingering menus so an open-toggle
        click always opens.  The harness deliberately has no opinion about
        what is safe to click elsewhere on the screen; the policy belongs
        to the application workflow.
        """
        try:
            if pre_open is not None:
                try:
                    pre_open()
                except Exception as e:
                    print(f"[open_ui_elements] pre_open hook failed: {e}", flush=True)
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
        pre_open=None,
    ) -> WorkflowResult:
        """Chain: click UI elements -> take screenshot -> query LLM.

        ``pre_open`` is passed through to :meth:`open_ui_elements` on every
        attempt (app-specific clearing policy; see there).
        """
        from ..screenshots import capture, crop_active_display
        from ..detection import parse_detection, DetectionParseError
        from pathlib import Path
        import time
        import os

        out_dir = Path("/tmp/opencode/gui")
        out_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_attempts):
            # Open UI elements
            res = self.open_ui_elements(clicks, delay_between_clicks, item_id=f"{item_id}.open_{attempt}", pre_open=pre_open)
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
                resp = self.driver.llm.send_message(prompt, [str(crop.path)])
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
