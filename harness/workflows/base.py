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
