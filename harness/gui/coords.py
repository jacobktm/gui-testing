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


# Cached display geometry (populated by get_display_resolution or early init).
_DISPLAY_GEOMETRY: dict | None = None

# Source resolutions for hardcoded coordinates.
COORD_SOURCE = {
    "pop-22.04": (1920, 1080),   # 16:9
    "pop-24.04": (1920, 1080),   # 16:9
    "ubuntu-26.04": (1920, 1200), # 16:10
}


def cache_display_geometry(*, force: bool = False) -> dict | None:
    """Call get_display() and cache the result. Call this during setup.

    On resumed runs (after reboot), force=True re-runs get_display() even if
    cached, since the display may not have been ready on the first attempt.
    """
    global _DISPLAY_GEOMETRY
    if _DISPLAY_GEOMETRY is not None and not force:
        return _DISPLAY_GEOMETRY
    import os
    resumed = os.environ.get("GUI_TESTING_RESUMED") == "1"
    if resumed:
        force = True
    # Retry a few times in case the display isn't ready after boot.
    for attempt in range(5):
        try:
            from ..display.display import get_display
            geom = get_display()
            if geom and geom.get("width", 0) > 0 and geom.get("height", 0) > 0:
                _DISPLAY_GEOMETRY = geom
                return geom
        except Exception:
            pass
        import time
        time.sleep(2)
    return _DISPLAY_GEOMETRY


def get_display_resolution() -> tuple[int, int]:
    """Return (width, height) of the primary display."""
    global _DISPLAY_GEOMETRY
    # Use cached geometry if available.
    if _DISPLAY_GEOMETRY is not None:
        w = _DISPLAY_GEOMETRY.get("width", 0)
        h = _DISPLAY_GEOMETRY.get("height", 0)
        if w > 0 and h > 0:
            return (w, h)
    # Try to populate cache.
    geom = cache_display_geometry()
    if geom is not None:
        return (geom["width"], geom["height"])
    # Try cosmic-randr.
    try:
        import subprocess, re
        result = subprocess.run(
            ["cosmic-randr", "list"], capture_output=True, text=True, timeout=5
        )
        ansi_re = re.compile(r'\x1b\[[0-9;]*m')
        clean = ansi_re.sub('', result.stdout)
        lines = clean.splitlines()
        current_display_pos = None
        current_mode = None
        primary_mode = None
        primary_found = False
        for line in lines:
            if not line.startswith(" ") and not line.startswith("\t") and line.strip() and "(" in line:
                if current_display_pos == (0, 0) and current_mode:
                    primary_mode = current_mode
                    primary_found = True
                current_display_pos = None
                current_mode = None
                continue
            stripped = line.strip()
            if stripped.startswith("Position:"):
                parts = stripped.split(":", 1)[1].strip().split(",")
                if len(parts) == 2:
                    try:
                        current_display_pos = (int(parts[0]), int(parts[1]))
                    except ValueError:
                        pass
            elif "current" in stripped:
                res = stripped.split()[0] if stripped.split() else ""
                res = re.sub(r'\x1b\[[0-9;]*m', '', res)
                if "x" in res:
                    try:
                        w, h = res.split("x")
                        current_mode = (int(w), int(h))
                    except ValueError:
                        pass
        if not primary_found and current_display_pos == (0, 0) and current_mode:
            primary_mode = current_mode
            primary_found = True
        if primary_mode is not None:
            return primary_mode
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
    # Try GTK/GDK monitors.
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
    # Fallback: assume 1920x1080.
    return (1920, 1080)

def adjust_coords(
    coords: tuple[float, float],
    src: tuple[int, int],
    dst: tuple[int, int] | None = None,
) -> tuple[float, float]:
    """Adjust normalized coordinates from source resolution to destination.

    Normalized coords are percentages of the display. Same aspect ratio = same percentages
    regardless of resolution. Different aspect ratios require transformation of both axes.
    """
    if dst is None:
        dst = get_display_resolution()
    src_w, src_h = src
    dst_w, dst_h = dst
    if src_w == dst_w and src_h == dst_h:
        return coords
    x, y = coords
    from math import gcd

    g1 = gcd(src_w, src_h)
    g2 = gcd(dst_w, dst_h)
    src_ar = (src_w // g1, src_h // g1)
    dst_ar = (dst_w // g2, dst_h // g2)

    def _same_ar(a, b):
        if a == b:
            return True
        try:
            return abs((a[0]/a[1]) - (b[0]/b[1])) < 0.001
        except Exception:
            return False

    # Same aspect ratio - normalized coords unchanged regardless of resolution
    if _same_ar(src_ar, dst_ar):
        return (x, y)

    # Different aspect ratios
    def _is_169(ar):
        return abs(ar[0]/ar[1] - 16/9) < 0.001
    def _is_1610(ar):
        return abs(ar[0]/ar[1] - 16/10) < 0.001 or abs(ar[0]/ar[1] - 8/5) < 0.001

    # Common case: 16:9 <-> 16:10
    if (_is_169(src_ar) and _is_1610(dst_ar)) or (_is_1610(src_ar) and _is_169(dst_ar)):
        py = y * src_h
        # UI elements anchored to right edge need offset-from-right to remain stable
        if x > 0.85:  # right-anchored (tray icons, menus on right)
            offset_right_norm = 1 - x
            # Keep pixel offset from right edge constant
            pixel_offset = offset_right_norm * src_w
            nx = 1 - (pixel_offset / dst_w)
            return (nx, py / dst_h)
        return (x, py / dst_h)

    # Ultrawide or other aspect ratios - both axes need transformation
    # Convert from source normalized space to destination normalized space
    src_ar_ratio = src_ar[0] / src_ar[1]
    dst_ar_ratio = dst_ar[0] / dst_ar[1]
    
    # Scale based on aspect ratio change
    # If going from 16:9 to 21:9 (wider), horizontal positions need adjustment
    aspect_scale = src_ar_ratio / dst_ar_ratio
    
    # For ultrawides, we need to scale x
    # This maintains relative positioning in the transformed coordinate space
    nx = x * aspect_scale
    # Adjust y as well for completeness
    ny = y  # often y is less affected, but better to be consistent
    
    # Alternative approach: treat as scaling from pixel space
    px = x * src_w
    py = y * src_h
    nx = px / dst_w
    ny = py / dst_h
    
    # Clamp to reasonable range
    if nx < 0 or nx > 1.5 or ny < 0 or ny > 1.5:  # allow slight overflow for ultrawides
        # Fallback to aspect-corrected scaling
        nx = x * aspect_scale
        ny = y
    
    return (max(0, min(1.5, nx)), max(0, min(1, ny)))
