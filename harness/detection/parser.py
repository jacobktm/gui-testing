from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["DetectionParseError", "DetectionResult", "parse_detection"]


class DetectionParseError(ValueError):
    """Raised when model output does not match the expected detection format."""


@dataclass(frozen=True)
class DetectionResult:
    value: str
    normalized: tuple[float, float] | None = None
    raw: str = ""
    extras: dict[str, Any] | None = None


_COORD_RE = re.compile(
    r"(?P<x>(?:[01](?:\.\d+)?)|(?:0?\.\d+))\s*[,\s]+\s*(?P<y>(?:[01](?:\.\d+)?)|(?:0?\.\d+))"
)
_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z\-_]+)\b")


def parse_detection(
    response: str | None,
    *,
    expected: set[str] | list[str] | tuple[str, ...] | None = None,
    allow_coords: bool = True,
) -> DetectionResult:
    if not response:
        raise DetectionParseError("empty response")

    text = response.strip()
    if not text:
        raise DetectionParseError("empty response")

    # Remove code fences
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
        text = text.strip()

    # Try to find normalized coordinates first
    normalized = None
    if allow_coords:
        match = _COORD_RE.search(text)
        if match:
            try:
                x = float(match.group("x"))
                y = float(match.group("y"))
                if 0 <= x <= 1 and 0 <= y <= 1:
                    normalized = (x, y)
            except ValueError:
                normalized = None

    # Extract word tokens as the primary value
    tokens = _WORD_RE.findall(text)
    value = None
    if expected:
        expected_set = {str(e).strip().lower() for e in expected}
        # Prefer the LAST token that matches expected (conclusion is usually at the end)
        for token in reversed(tokens):
            if token.lower() in expected_set:
                value = token
                break
        # Then try multi-word match (e.g., "Power Saver" in text) - prefer last occurrence
        if value is None:
            text_lower = text.lower()
            for exp in sorted(expected_set, key=len, reverse=True):
                # Find last occurrence
                idx = text_lower.rfind(exp)
                if idx >= 0:
                    value = exp
                    break
    if value is None and tokens:
        value = tokens[-1]  # Use last token as fallback
    if value is None:
        # Fallback: take last alphanumeric sequence
        matches = list(re.finditer(r"([A-Za-z][A-Za-z\-_]+)", text))
        if matches:
            value = matches[-1].group(1)

    if value is None:
        raise DetectionParseError(f"could not parse value from response: {text!r}")

    if expected:
        expected_set = {str(e).strip().lower() for e in expected}
        if value.lower() not in expected_set:
            # Check if value is a substring match.
            val_lower = value.lower()
            if not any(val_lower in exp or exp in val_lower for exp in expected_set):
                raise DetectionParseError(
                    f"value {value!r} not in expected {sorted(expected_set)}"
                )

    return DetectionResult(value=value, normalized=normalized, raw=response)
