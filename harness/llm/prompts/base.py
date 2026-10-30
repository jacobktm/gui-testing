from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PromptTemplate:
    """Base class for prompt templates with placeholder substitution."""

    template: str
    required: set[str] | None = None

    def render(self, **kwargs: Any) -> str:
        if self.required:
            missing = self.required - set(kwargs.keys())
            if missing:
                raise ValueError(f"Missing required placeholders: {missing}")
        return self.template.format(**kwargs)

    def __call__(self, **kwargs: Any) -> str:
        return self.render(**kwargs)
