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
    # Try cosmic-randr first (COSMIC native).
    try:
        import subprocess, re
        result = subprocess.run(
            ["cosmic-randr", "list"], capture_output=True, text=True, timeout=5
        )
        # Strip ANSI color codes.
        ansi_re = re.compile(r'\x1b\[[0-9;]*m')
        clean = ansi_re.sub('', result.stdout)
        # Parse output: find display at position 0,0, get its current mode.
        lines = clean.splitlines()
        current_display_pos = None
        current_mode = None
        in_modes = False
        primary_mode = None
        primary_found = False
        for line in lines:
            # Display header: "eDP-1 (enabled)" or "DP-3 (enabled)"
            if not line.startswith(" ") and not line.startswith("\t") and line.strip() and "(" in line:
                # New display. Check if previous was primary.
                if current_display_pos == (0, 0) and current_mode:
                    primary_mode = current_mode
                    primary_found = True
                current_display_pos = None
                current_mode = None
                in_modes = False
                continue
            stripped = line.strip()
            if stripped.startswith("Position:"):
                parts = stripped.split(":", 1)[1].strip().split(",")
                if len(parts) == 2:
                    try:
                        current_display_pos = (int(parts[0]), int(parts[1]))
                    except ValueError:
                        pass
            elif stripped.startswith("Modes:"):
                in_modes = True
            elif in_modes and "current" in stripped:
                # "3840x2160 @ 144.001 Hz (current) (preferred)"
                res = stripped.split()[0]
                res = re.sub(r'\x1b\[[0-9;]*m', '', res)
                if "x" in res:
                    try:
                        w, h = res.split("x")
                        current_mode = (int(w), int(h))
                    except ValueError:
                        pass
        # Check last display.
        if not primary_found and current_display_pos == (0, 0) and current_mode:
            primary_mode = current_mode
            primary_found = True
        # If no primary found, use first display with a mode.
        if primary_mode is None:
            # Re-parse to find any display with a current mode.
            for line in lines:
                stripped = line.strip()
                if stripped and "current" in stripped and "x" in stripped.split()[0] if stripped.split() else False:
                    res = stripped.split()[0]
                    if "x" in res:
                        try:
                            w, h = res.split("x")
                            primary_mode = (int(w), int(h))
                            break
                        except ValueError:
                            pass
        if primary_mode is not None:
            return primary_mode
    except Exception:
        pass
    # Try wlr-randr
    try:
        import subprocess
        result = subprocess.run(
            ["wlr-randr"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            # "DP-1 "..." (connected)"
            # "  1920x1080 @ 60.000 Hz (preferred)"
            line = line.strip()
            if "x" in line and "@" in line:
                parts = line.split()
                res = parts[0]
                if "x" in res:
                    w, h = res.split("x")
                    w, h = int(w), int(h)
                    if w > 0 and h > 0:
                        return (w, h)
    except Exception:
        pass
    # Try xrandr.
    try:
        import subprocess
        result = subprocess.run(
            ["xrandr"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "*" in line:
                parts = line.strip().split()
                if parts:
                    res = parts[0]
                    if "x" in res:
                        w, h = res.split("x")
                        w, h = int(w), int(h)
                        if w > 0 and h > 0:
                            return (w, h)
    except Exception:
        pass
    # Try GTK/GDK.
    try:
        from .display import get_monitors
        monitors = get_monitors()
        if monitors:
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
    # Try reading from /sys/class/drm (kernel framebuffer).
    try:
        import os, glob
        for path in sorted(glob.glob("/sys/class/drm/card*/modes")):
            try:
                with open(path) as f:
                    mode = f.readline().strip()
                    if "x" in mode:
                        w, h = mode.split("x")[:2]
                        w, h = int(w), int(h)
                        if w > 0 and h > 0:
                            return (w, h)
            except Exception:
                pass
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
