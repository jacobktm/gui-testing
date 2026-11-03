"""Pop!_OS base flavor.

Used as the fallback for Pop!_OS versions without a dedicated flavor (for
example ``pop-25.04``).  It carries the behavior of the most recent release
(COSMIC-era) so a new release works out of the box; add a dedicated flavor
module only when that release actually differs.
"""

from __future__ import annotations

from ..base import PlatformFlavor
from ..registry import register_flavor


@register_flavor
class PopOSBaseFlavor(PlatformFlavor):
    name = "popos"
    matches = ["pop-"]
    priority = 1
    family = "popos"

    def get_coord_source(self) -> tuple[int, int]:
        return (1920, 1080)

    def get_open_clicks(self) -> list[tuple[float, float]]:
        from harness.gui import Coords
        return [(Coords.OPEN[0], Coords.OPEN[1])]

    def get_profile_coords(self, profile: str) -> tuple[float, float] | None:
        from harness.gui import Coords
        return Coords.POP_24.get(f"profile_{profile}")

    def get_profile_prompt(self):
        from harness.llm.prompts import SIMPLE_SELECTION
        return SIMPLE_SELECTION.render(
            item="power profile",
            choices="'performance', 'battery', or 'balanced'",
            extra_instructions="Power Saver is the same as 'battery'.",
        )

    def get_profile_expected(self) -> set[str]:
        return {"performance", "balanced", "battery", "battery saver", "batterysaver"}

    def normalize_profile(self, value: str) -> str:
        value = str(value).lower()
        if value in ("power saver", "battery saver", "batterysaver", "powersaver"):
            return "battery"
        elif value == "high performance":
            return "performance"
        return value

    def get_graphics_prompt(self):
        from harness.llm.prompts import SINGLE_WORD_CHOICE
        return SINGLE_WORD_CHOICE.render(
            context="graphics settings",
            item="graphics mode",
            choices="'integrated', 'hybrid', 'compute', or 'nvidia'",
        )

    def get_graphics_expected(self) -> set[str]:
        return {"integrated", "hybrid", "compute", "nvidia"}

    def supports_graphics_switching(self) -> bool:
        # COSMIC-era releases do not expose graphics switching to the GUI.
        return False

    def get_click_delay(self) -> float:
        return 2.0

    def get_wait_after_clicks(self) -> float:
        return 6.0
