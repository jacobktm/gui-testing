"""Base classes for platform flavors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PlatformInfo:
    """Detected platform information."""
    os_id: str  # e.g., "pop-24.04", "ubuntu-26.04"
    os_name: str  # e.g., "Pop!_OS", "Ubuntu"
    version: str  # e.g., "24.04", "26.04"
    codename: str | None = None
    desktop: str | None = None  # e.g., "cosmic", "gnome"
    session_type: str | None = None  # e.g., "wayland", "x11"
    family: str | None = None  # e.g., "popos", "ubuntu"
    major: int | None = None
    minor: int | None = None


class PlatformFlavor:
    """Base class for OS/desktop flavor implementations."""
    
    # Flavor identification
    name: str = "base"
    matches: list[str] = []  # os_id patterns or full matches
    priority: int = 0  # higher priority wins if multiple match
    family: str | None = None
    min_version: tuple[int, int] | None = None
    max_version: tuple[int, int] | None = None
    
    def __init__(self, info: PlatformInfo | None = None):
        self.info = info
        if info and not info.family and self.family:
            info.family = self.family
    
    def matches_os_id(self, os_id: str) -> bool:
        """Check if this flavor handles the given os_id."""
        for pattern in self.matches:
            if pattern == os_id or os_id.startswith(pattern + "-") or os_id == pattern or os_id.startswith(pattern):
                return True
        return False
    
    def matches_info(self, info: PlatformInfo) -> bool:
        """Check if this flavor handles the given platform info."""
        if self.matches_os_id(info.os_id):
            return True
        # Family + version range matching
        if self.family and info.family and self.family == info.family:
            if info.major is not None:
                if self.min_version and (info.major, info.minor or 0) < self.min_version:
                    return False
                if self.max_version and (info.major, info.minor or 0) > self.max_version:
                    return False
                # If flavor has version constraints and we're in range/family match, accept
                if self.min_version or self.max_version:
                    return True
            elif not self.matches and self.family == info.family:
                # Family base flavor
                return True
        return False
    
    # Coordinate/configuration
    def get_coord_source(self) -> tuple[int, int]:
        """Source resolution for predefined coordinates."""
        return (1920, 1080)
    
    def get_open_clicks(self) -> list[tuple[float, float]]:
        """Clicks needed to open settings/power panel."""
        from harness.gui import Coords
        return [(Coords.OPEN[0], Coords.OPEN[1])]
    
    def get_extra_clicks(self) -> list[tuple[float, float]]:
        """Additional clicks after opening."""
        return []

    def get_profile_coords(self, profile: str) -> tuple[float, float] | None:
        """Coordinates of a power profile entry once settings are open.

        Flavors that can place their profile rows predictably return the
        coordinate here; returning ``None`` means the caller should fall back
        to vision-based detection.
        """
        return None

    def get_graphics_coords(self, mode: str) -> tuple[float, float] | None:
        """Coordinates of a graphics mode entry once settings are open."""
        return None
    
    # Prompts
    def get_profile_prompt(self):
        """Prompt template for power profile detection."""
        from harness.llm.prompts import SIMPLE_SELECTION
        return SIMPLE_SELECTION.render(
            item="power profile",
            choices="'performance', 'battery', or 'balanced'",
            extra_instructions="Power Saver is the same as 'battery'.",
        )
    
    def get_profile_expected(self) -> set[str]:
        """Expected values for profile detection."""
        return {"performance", "balanced", "battery", "battery saver", "batterysaver"}
    
    def normalize_profile(self, value: str) -> str:
        """Normalize detected profile value."""
        value = value.lower()
        if value in ("power saver", "battery saver", "batterysaver", "powersaver"):
            return "battery"
        elif value == "high performance":
            return "performance"
        return value
    
    def get_graphics_prompt(self):
        """Prompt for graphics mode detection."""
        from harness.llm.prompts import SINGLE_WORD_CHOICE
        return SINGLE_WORD_CHOICE.render(
            context=f"{self.info.os_name if self.info else 'Linux'} graphics settings",
            item="graphics mode",
            choices="'integrated', 'hybrid', 'compute', or 'nvidia'",
        )
    
    def get_graphics_expected(self) -> set[str]:
        return {"integrated", "hybrid", "compute", "nvidia"}
    
    def supports_graphics_switching(self) -> bool:
        """Whether this platform supports graphics mode switching."""
        return False
    
    # UI behavior
    def get_click_delay(self) -> float:
        return 3.0
    
    def get_wait_after_clicks(self) -> float:
        return 8.0
    
    # Custom behavior hooks
    def pre_open_hook(self, driver) -> None:
        """Called before opening settings."""
        pass
    
    def post_click_hook(self, driver) -> None:
        """Called after clicks."""
        pass
