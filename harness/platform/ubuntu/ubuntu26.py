"""Ubuntu flavors."""

from __future__ import annotations

from ..base import PlatformFlavor
from ..registry import register_flavor


@register_flavor
class Ubuntu26Flavor(PlatformFlavor):
    name = "ubuntu-26.04"
    matches = ["ubuntu-26.04"]
    priority = 20
    family = "ubuntu"
    min_version = (26, 0)
    max_version = (26, 99)
    
    def get_coord_source(self) -> tuple[int, int]:
        return (1920, 1200)
    
    def get_open_clicks(self) -> list[tuple[float, float]]:
        from harness.gui import Coords
        clicks = [(Coords.OPEN[0], Coords.OPEN[1])]
        extra = Coords.UBUNTU_26.get("extra_click")
        if extra:
            clicks.append((extra[0], extra[1]))
        return clicks
    
    def get_extra_clicks(self) -> list[tuple[float, float]]:
        from harness.gui import Coords
        extra = Coords.UBUNTU_26.get("extra_click")
        return [(extra[0], extra[1])] if extra else []
    
    def get_profile_prompt(self):
        from harness.llm.prompts import SETTINGS_SELECTION
        return SETTINGS_SELECTION.render(
            app_name="power/power mode",
            settings_section="settings",
            item_type="power mode",
            choices="'performance', 'balanced', or 'battery'",
            extra_instructions="If it says 'Power Saver', answer 'battery'. If it says 'Performance', answer 'performance'.",
        )
    
    def get_profile_expected(self) -> set[str]:
        return {"performance", "balanced", "battery", "power saver", "powersaver"}
    
    def normalize_profile(self, value: str) -> str:
        value = value.lower()
        if value in ("power saver", "powersaver"):
            return "battery"
        elif value == "high performance":
            return "performance"
        return value
    
    def supports_graphics_switching(self) -> bool:
        return False
    
    def get_click_delay(self) -> float:
        return 3.0
    
    def get_wait_after_clicks(self) -> float:
        return 8.0
