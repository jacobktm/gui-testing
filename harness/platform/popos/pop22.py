"""Pop!_OS 22.04 flavor (GNOME Shell)."""

from __future__ import annotations

from ..base import PlatformFlavor
from ..registry import register_flavor


@register_flavor
class Pop22Flavor(PlatformFlavor):
    name = "popos-22.04"
    matches = ["pop-22.04"]
    priority = 20
    family = "popos"
    min_version = (22, 0)
    max_version = (22, 99)

    def get_coord_source(self) -> tuple[int, int]:
        return (1920, 1080)

    def get_open_clicks(self) -> list[tuple[float, float]]:
        """Click the system menu / battery indicator."""
        from harness.gui import Coords
        return [(Coords.OPEN[0], Coords.OPEN[1])]

    def get_extra_clicks(self) -> list[tuple[float, float]]:
        """The system menu has a separate power/gear entry to expand."""
        from harness.gui import Coords
        return [(Coords.POP22_EXTRA[0], Coords.POP22_EXTRA[1])]

    def get_profile_coords(self, profile: str) -> tuple[float, float] | None:
        from harness.gui import Coords
        return Coords.POP22_PROFILES.get(profile)

    def get_graphics_coords(self, mode: str) -> tuple[float, float] | None:
        from harness.gui import Coords
        return Coords.POP22_GRAPHICS.get(mode)

    def get_profile_prompt(self):
        from harness.llm.prompts import SIMPLE_SELECTION
        return SIMPLE_SELECTION.render(
            item="power profile",
            choices="'performance', 'battery', or 'balanced'",
            extra_instructions="Power Saver is the same as 'battery'.",
        )

    def get_profile_expected(self) -> set[str]:
        return {"performance", "balanced", "battery", "battery saver", "batterysaver"}

    def get_graphics_prompt(self):
        from harness.llm.prompts import SINGLE_WORD_CHOICE
        return SINGLE_WORD_CHOICE.render(
            context="Pop!_OS 22.04 graphics settings",
            item="graphics mode",
            choices="'integrated', 'hybrid', 'compute', or 'nvidia'",
        )

    def supports_graphics_switching(self) -> bool:
        return True

    def get_click_delay(self) -> float:
        return 2.0

    def get_wait_after_clicks(self) -> float:
        return 5.0
