from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowResult:
    success: bool
    item_id: str | None = None
    summary: str = ""
    data: dict[str, Any] | None = None


class Workflow:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts

    def run(self, *args, **kwargs) -> WorkflowResult:
        raise NotImplementedError

    def resume_progress(self, item_id: str, *, kind: str, phase: str = "state") -> dict[str, Any]:
        """Return persisted progress of ``kind`` for ``item_id``.

        The state document is written by :meth:`persist_state`; when it is
        missing or belongs to a different kind of test, an empty dict is
        returned so callers can start from scratch.
        """
        state = self.load_persisted_state(item_id, phase=phase)
        if isinstance(state, dict) and state.get("kind") == kind:
            return state
        return {}

    def persist_state(
        self,
        item_id: str,
        phase: str,
        state: dict[str, Any],
        *,
        step: str = "state",
    ) -> None:
        """Best-effort persistence of named state via the artifacts store."""
        if self.artifacts is None or not item_id:
            return
        try:
            self.artifacts.save_state(item_id, phase, state, step=step)
        except Exception:
            pass

    def load_persisted_state(self, item_id: str, phase: str = "state") -> dict[str, Any] | None:
        """Load the newest persisted state document for an item/phase, if any."""
        if self.artifacts is None or not item_id:
            return None
        try:
            return self.artifacts.load_state(item_id, phase=phase)
        except Exception:
            return None
