from __future__ import annotations

__all__ = ["Coords"]


class Coords:
    """Predictable normalized coordinates for known layouts.

    Pop!_OS 24.04 is the baseline for all three OSes.
    Pop!_OS 22.04 needs one additional click.
    Ubuntu 26.04 uses different labels (e.g. 'Power Saver').
    """

    # Pop!_OS 24.04 (baseline)
    POP_24 = {
        "open_settings": (0.05, 0.05),
        "power_tab": (0.15, 0.25),
        "profile_battery": (0.4, 0.35),
        "profile_balanced": (0.4, 0.42),
        "profile_performance": (0.4, 0.49),
    }

    # Pop!_OS 22.04 - needs extra click compared to 24.04
    POP_22 = {
        **POP_24,
        "extra_click": (0.5, 0.2),  # Pop 22.04 specific adjustment
        "graphics_tab": (0.15, 0.35),
    }

    # Ubuntu 26.04 - similar layout to baseline but different labels
    UBUNTU_26 = {
        **POP_24,
        "power_tab": (0.15, 0.28),  # slight adjustment if needed
    }
