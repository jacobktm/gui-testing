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


# Source resolutions for hardcoded coordinates.
COORD_SOURCE = {
    "pop-22.04": (1920, 1080),   # 16:9
    "pop-24.04": (1920, 1080),   # 16:9
    "ubuntu-26.04": (1920, 1200), # 16:10
}


def get_display_resolution() -> tuple[int, int]:
    """Return (width, height) of the primary display."""
    # Try GTK/GDK first — use the primary monitor (x=0, y=0).
    try:
        from .display import get_monitors
        monitors = get_monitors()
        if monitors:
            # Find primary monitor (top-left origin).
            primary = None
            for m in monitors:
                if m.get("x", -1) == 0 and m.get("y", -1) == 0:
                    primary = m
                    break
            if primary is None:
                primary = monitors[0]
            if primary.get("width", 0) > 0 and primary.get("height", 0) > 0:
                return (primary["width"], primary["height"])
    except Exception:
        pass
    # Fallback: xrandr.
    try:
        import subprocess
        result = subprocess.run(
            ["xrandr"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "*" in line:
                # "   1920x1080    143.88*+"
                parts = line.strip().split()
                if parts:
                    res = parts[0]
                    if "x" in res:
                        w, h = res.split("x")
                        return (int(w), int(h))
    except Exception:
        pass
    # Fallback: assume 1920x1080.
    return (1920, 1080)


def adjust_coords(
    coords: tuple[float, float],
    src: tuple[int, int],
    dst: tuple[int, int] | None = None,
) -> tuple[float, float]:
    """Adjust normalized coordinates from source resolution to destination.

    If the UI uses fixed pixel positions, normalized coords change with
    resolution.  This converts from the resolution the coords were measured
    on to the actual display resolution.
    """
    if dst is None:
        dst = get_display_resolution()
    src_w, src_h = src
    dst_w, dst_h = dst
    if src_w == dst_w and src_h == dst_h:
        return coords
    x, y = coords
    # Convert normalized -> pixels -> normalized.
    px = x * src_w
    py = y * src_h
    return (px / dst_w, py / dst_h)
