"""Set-of-Mark (SoM) UI element detection.

Uses OpenCV to detect UI elements in a screenshot, annotates them with
numbered IDs, and asks Ollama to identify which ID corresponds to a
target element.  The coordinates are then looked up from the element map.

This is more reliable than asking Ollama for raw coordinates, because
LLMs are good at identifying labeled elements but bad at precise
coordinate detection.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def generate_set_of_mark(
    image_path: str | Path,
    output_path: str | Path | None = None,
    min_size: int = 10,
    max_ratio: float = 0.9,
) -> tuple[str, dict[int, tuple[int, int]]]:
    """Detect UI elements via OpenCV and annotate with numbered IDs.

    Returns (output_path, element_map) where element_map maps
    ID -> (center_x, center_y) in pixel coordinates.
    """
    if not HAS_CV2:
        raise RuntimeError("opencv-python not installed")

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Could not load {image_path}")

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, threshold1=50, threshold2=150)
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Gather valid bounding boxes.
    ui_rects = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if min_size < bw < (w * max_ratio) and min_size < bh < (h * max_ratio):
            ui_rects.append([x, y, bw, bh])

    occupied = list(ui_rects)
    element_map = {}
    element_id = 1
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    thickness = 1

    for rect in ui_rects:
        bx, by, bw, bh = rect
        cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (0, 255, 0), 1)

        text_str = str(element_id)
        (tw, th), baseline = cv2.getTextSize(text_str, font, font_scale, thickness)

        candidates = [
            (bx, by + bh + th + 4, [bx, by + bh + 4 - th, tw, th + baseline]),
            (bx, by - 4, [bx, by - 4 - th, tw, th + baseline]),
            (bx + bw + 4, by + (bh + th) // 2, [bx + bw + 4, by + (bh - th) // 2, tw, th + baseline]),
            (bx - tw - 4, by + (bh + th) // 2, [bx - tw - 4, by + (bh - th) // 2, tw, th + baseline]),
        ]

        chosen_pos = None
        for text_x, text_y, text_rect in candidates:
            if (text_rect[0] < 0 or text_rect[1] < 0 or
                    text_rect[0] + text_rect[2] > w or
                    text_rect[1] + text_rect[3] > h):
                continue
            collision = False
            for obstacle in occupied:
                if obstacle is rect:
                    continue
                # check_collision
                x1, y1, w1, h1 = text_rect
                x2, y2, w2, h2 = obstacle
                if not (x1 + w1 + 2 < x2 or x2 + w2 + 2 < x1 or y1 + h1 + 2 < y2 or y2 + h2 + 2 < y1):
                    collision = True
                    break
            if not collision:
                chosen_pos = (text_x, text_y)
                occupied.append(text_rect)
                break

        if not chosen_pos:
            chosen_pos = (bx + 2, by + th + 2)

        # OCR the element text for a label.
        label_text = ocr_element_text(image_path, (bx, by, bw, bh))
        label_text = label_text.strip()[:20]

        cv2.putText(img, text_str, chosen_pos, font, font_scale, (0, 255, 0), thickness)

        # Draw label below the ID if OCR found text.
        if label_text:
            label_pos = (chosen_pos[0], chosen_pos[1] + th + 4)
            cv2.putText(img, label_text, label_pos, font, font_scale * 0.8, (255, 255, 0), thickness)

        center_x = bx + (bw // 2)
        center_y = by + (bh // 2)
        element_map[element_id] = (center_x, center_y, label_text)
        element_id += 1

    if output_path is None:
        output_path = str(image_path).replace(".", "_som.")
    cv2.imwrite(str(output_path), img)
    return str(output_path), element_map


def ocr_element_text(image_path: str, bbox: tuple) -> str:
    """Use tesseract to OCR text from a bounding box region."""
    if not HAS_CV2:
        return ""
    try:
        import subprocess
        import cv2
        img = cv2.imread(str(image_path))
        if img is None:
            return ""
        x, y, w, h = bbox
        pad = 4
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img.shape[1], x + w + pad)
        y2 = min(img.shape[0], y + h + pad)
        crop = img[y1:y2, x1:x2]
        crop_path = str(image_path).replace(".", "_crop.", 1)
        cv2.imwrite(crop_path, crop)
        result = subprocess.run(
            ["tesseract", crop_path, "stdout", "--psm", "7"],
            capture_output=True, text=True, timeout=10,
        )
        text = result.stdout.strip()
        try:
            os.remove(crop_path)
        except OSError:
            pass
        return text
    except Exception:
        return ""


def ask_vlm_for_element(
    annotated_image_path: str,
    target_description: str,
    model: str = "qwen3-vl:8b",
    ip: str = "127.0.0.1",
    port: str = "11434",
) -> int | None:
    """Ask Ollama which numbered ID corresponds to the target element."""
    import ollama as _ollama
    client = _ollama.Client(host=f"http://{ip}:{port}")
    prompt = f"Scan this annotated screenshot. Each green box has an ID number and possibly a text label. What is the green ID number next to the {target_description}? State only the number."
    try:
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt, "images": [annotated_image_path]}],
            options={"num_ctx": 8192},
        )
        raw = response["message"]["content"].strip()
        match = re.search(r"\d+", raw)
        if match:
            return int(match.group(0))
    except Exception:
        pass
    return None


def detect_element_coords(
    image_path: str | Path,
    target_description: str,
    *,
    ollama_ip: str = "127.0.0.1",
    ollama_port: str = "11434",
    ollama_model: str = "qwen3-vl:8b",
    min_size: int = 10,
) -> tuple[float, float] | None:
    """Full pipeline: detect elements, annotate, ask VLM, return normalized coords.

    Returns (x, y) in 0-1 range, or None if detection fails.
    """
    img = cv2.imread(str(image_path)) if HAS_CV2 else None
    if img is None:
        return None
    h, w = img.shape[:2]

    som_path, element_map = generate_set_of_mark(image_path)
    if not element_map:
        return None

    selected_id = ask_vlm_for_element(
        som_path, target_description,
        model=ollama_model, ip=ollama_ip, port=ollama_port,
    )
    if selected_id is None or selected_id not in element_map:
        return None

    entry = element_map[selected_id]
    cx, cy = entry[0], entry[1]
    return (cx / w, cy / h)
