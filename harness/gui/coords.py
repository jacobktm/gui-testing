from __future__ import annotations

__all__ = ["Coords"]


class Coords:
    """Predictable normalized coordinates for known layouts."""

    OPEN = (0.955, 0.014)
    POP22_EXTRA = (0.955, 0.20)

    POP22_PROFILES = {
        "performance": (0.955, 0.6),
        "balanced": (0.955, 0.55),
        "battery": (0.955, 0.52),
    }
    POP22_GRAPHICS = {
        "compute": (0.955, 0.45),
        "hybrid": (0.955, 0.4),
        "nvidia": (0.955, 0.35),
        "integrated": (0.955, 0.3),
    }

    POP_24 = {
        "open_settings": OPEN,
        "profile_battery": (0.955, 0.52),
        "profile_balanced": (0.955, 0.55),
        "profile_performance": (0.955, 0.6),
    }
    UBUNTU_26 = {
        "open_settings": OPEN,
        "profile_battery": (0.955, 0.52),
        "profile_balanced": (0.955, 0.55),
        "profile_performance": (0.955, 0.6),
    }
    POP_22 = {
        "open_settings": OPEN,
        "extra_click": POP22_EXTRA,
        **POP22_PROFILES,
        **{f"graphics_{k}": v for k, v in POP22_GRAPHICS.items()},
    }
