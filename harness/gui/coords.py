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
        # Pop!_OS 24.04: profile positions observed after the initial settings click.
        "profile_battery": (0.955, 0.13),
        "profile_balanced": (0.955, 0.18),
        "profile_performance": (0.955, 0.24),
    }
    UBUNTU_26 = {
        "open_settings": OPEN,
        "extra_click": (0.875, 0.23),
        "profile_battery": (0.875, 0.325),
        "profile_balanced": (0.875, 0.39),
        "profile_performance": (0.875, 0.35),
    }
    UBUNTU_26_DISMISS = (0.1, 0.1)  # click outside twice or press esc

    POP_22 = {
        "open_settings": OPEN,
        "extra_click": POP22_EXTRA,
        **POP22_PROFILES,
        **{f"graphics_{k}": v for k, v in POP22_GRAPHICS.items()},
    }
