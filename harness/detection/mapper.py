from __future__ import annotations

__all__ = ["map_normalized_to_screen", "to_dotool_normalized"]


def to_dotool_normalized(normalized: tuple[float, float]) -> tuple[float, float]:
    """Pass normalized coordinates through for dotool.mouseto.

    dotool's mouseto expects normalized coordinates (0-1) constrained to
    the window/display the mouse is in. The model returns coordinates
    normalized relative to the cropped active display image, so they can
    be passed directly.
    """
    nx, ny = normalized
    if not (0 <= nx <= 1 and 0 <= ny <= 1):
        raise ValueError(f"normalized coordinates must be in [0,1]: {(nx, ny)}")
    return (float(nx), float(ny))


def map_normalized_to_screen(
    normalized: tuple[float, float],
    *,
    origin: tuple[int, int] = (0, 0),
    crop_width: int | None = None,
    crop_height: int | None = None,
    display_scale: float = 1.0,
    image_scale: float = 1.0,
) -> tuple[int, int]:
    """Map normalized coordinates from a cropped display to absolute screen pixels.

    This is only needed if something requires absolute coordinates.
    dotool.mouseto uses :func:`to_dotool_normalized`.
    """
    nx, ny = normalized
    if not (0 <= nx <= 1 and 0 <= ny <= 1):
        raise ValueError(f"normalized coordinates must be in [0,1]: {(nx, ny)}")

    ox, oy = origin
    if crop_width is not None and crop_height is not None:
        x = ox + nx * crop_width
        y = oy + ny * crop_height
    else:
        x = ox + nx
        y = oy + ny

    if image_scale and image_scale != 1:
        x = x / image_scale
        y = y / image_scale

    return (int(round(x)), int(round(y)))
