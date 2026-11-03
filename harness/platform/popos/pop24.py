"""Pop!_OS 24.04 flavor (COSMIC)."""

from __future__ import annotations

from ..base import PlatformFlavor
from ..registry import register_flavor


@register_flavor
class Pop24Flavor(PlatformFlavor):
    name = "popos-24.04"
    matches = ["pop-24.04"]
    priority = 20
    family = "popos"
    min_version = (24, 0)
    max_version = (24, 99)
    
    def get_coord_source(self) -> tuple[int, int]:
        return (1920, 1080)
    
    def get_open_clicks(self) -> list[tuple[float, float]]:
        from harness.gui import Coords
        return [(Coords.OPEN[0], Coords.OPEN[1])]
    
    def get_profile_prompt(self):
        from harness.llm.prompts import SIMPLE_SELECTION
        return SIMPLE_SELECTION.render(
            item="power profile",
            choices="'performance', 'battery', or 'balanced'",
            extra_instructions="Power Saver is the same as 'battery'.",
        )
    
    def get_profile_expected(self) -> set[str]:
        return {"performance", "balanced", "battery", "battery saver", "batterysaver"}
    
    def supports_graphics_switching(self) -> bool:
        return False  # COSMIC handles differently
    
    def get_click_delay(self) -> float:
        return 2.0
    
    def get_wait_after_clicks(self) -> float:
        return 6.0
