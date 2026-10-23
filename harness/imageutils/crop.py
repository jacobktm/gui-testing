from pathlib import Path
from PIL import Image
import math

__all__ = ["crop", "scale_crop_box"]


def scale_crop_box(origin: tuple[int, int],
                   width: int,
                   height: int,
                   scale: float) -> tuple[tuple[int, int], int, int]:
    x, y = origin[0], origin[1]
    x0 = math.floor(x * scale)
    y0 = math.floor(y * scale)
    w_px = math.floor(width * scale)
    h_px = math.floor(height * scale)
    return (x0, y0), w_px, h_px


def crop(input_path: Path, origin: tuple[int, int], width: int, height: int, output_path: Path):
    x, y = origin[0], origin[1]
    with Image.open(input_path, 'r') as img:
        box = (x, y, x + width, y + height)
        if x < 0 or y < 0 or box[2] > img.width or box[3] > img.height:
            raise ValueError(
                    f"crop box {box} exceeds image bounds {img.width}x{img.height}"
            )
        img.crop(box).save(output_path)
