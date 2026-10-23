import subprocess
import time
import math

__all__ = [
    "drag_and_drop",
    "left_click",
    "right_click",
    "middle_click",
    "click",
    "mouse_down",
    "mouse_up",
    "mouseto",
    "key",
    "key_down",
    "key_up",
    "send_keys",
    "type_text",
]


def _calculate_steps(
    start: tuple[float, float],
    end: tuple[float, float],
    width: int = 1920,
    height: int = 1080,
    step_px=4.0,
):
    start_x, start_y = start[0] * width, start[1] * height
    end_x, end_y = end[0] * width, end[1] * height
    distance = math.hypot(end_x - start_x, end_y - start_y)
    return max(1, math.ceil(distance / step_px))


def _ensure_process(dtproc=None):
    if dtproc is not None:
        return dtproc, False
    proc = subprocess.Popen(["dotool"], stdin=subprocess.PIPE, text=True)
    return proc, True


def _dotool_send(commands: str, dtproc=None):
    proc, own = _ensure_process(dtproc)
    try:
        proc.stdin.write(commands)
        if not commands.endswith("\n"):
            proc.stdin.write("\n")
        proc.stdin.flush()
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def send_keys(keys: str, dtproc=None):
    if isinstance(keys, (list, tuple)):
        keys = "\n".join(keys)
    return _dotool_send(keys, dtproc=dtproc)


def key_down(key: str, dtproc=None):
    return _dotool_send(f"keydown {key}", dtproc=dtproc)


def key_up(key: str, dtproc=None):
    return _dotool_send(f"keyup {key}", dtproc=dtproc)


def key(key: str, press: bool = True, dtproc=None):
    if press:
        return _dotool_send(f"key {key}", dtproc=dtproc)
    return key_down(key, dtproc=dtproc)


def type_text(text: str, delay: float = 0.05, dtproc=None):
    proc, own = _ensure_process(dtproc)
    try:
        for char in text:
            if char == "\n":
                proc.stdin.write("key enter\n")
            elif char == "\t":
                proc.stdin.write("key tab\n")
            elif char == " ":
                proc.stdin.write("key space\n")
            else:
                proc.stdin.write(f"type {char}\n")
            proc.stdin.flush()
            if delay > 0:
                time.sleep(delay)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def drag_and_drop(
    start: tuple[float, float],
    paths: list[tuple[float, float]],
    width: int = 1920,
    height: int = 1080,
    dtproc=None,
):
    proc, own = _ensure_process(dtproc)
    try:
        mouseto(start, dtproc=proc, delay=0.5)
        mouse_down("left", dtproc=proc)
        time.sleep(0.5)

        path_start = start

        for path_end in paths:
            steps = _calculate_steps(path_start, path_end, width, height)

            for i in range(1, steps + 1):
                cx = path_start[0] + (path_end[0] - path_start[0]) * (i / steps)
                cy = path_start[1] + (path_end[1] - path_start[1]) * (i / steps)
                mouseto((cx, cy), dtproc=proc, delay=0.01)

            path_start = path_end

        time.sleep(0.05)
        mouse_up("left", dtproc=proc)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def mouseto(dest: tuple[float, float] = (0.0, 0.0), dtproc=None, delay: float = 0.05):
    proc, own = _ensure_process(dtproc)
    try:
        proc.stdin.write(f"mouseto {dest[0]} {dest[1]}\n")
        proc.stdin.flush()
        time.sleep(delay)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def click(button: str = "left", dtproc=None, delay: float = 0.05):
    proc, own = _ensure_process(dtproc)
    try:
        proc.stdin.write(f"click {button}\n")
        proc.stdin.flush()
        time.sleep(delay)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def left_click(dtproc=None, delay: float = 0.05):
    return click("left", dtproc=dtproc, delay=delay)


def right_click(dtproc=None, delay: float = 0.05):
    return click("right", dtproc=dtproc, delay=delay)


def middle_click(dtproc=None, delay: float = 0.05):
    return click("middle", dtproc=dtproc, delay=delay)


def mouse_down(button: str = "left", dtproc=None, delay: float = 0.05):
    proc, own = _ensure_process(dtproc)
    try:
        proc.stdin.write(f"buttondown {button}\n")
        proc.stdin.flush()
        time.sleep(delay)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc


def mouse_up(button: str = "left", dtproc=None, delay: float = 0.05):
    proc, own = _ensure_process(dtproc)
    try:
        proc.stdin.write(f"buttonup {button}\n")
        proc.stdin.flush()
        time.sleep(delay)
    finally:
        if own:
            proc.stdin.close()
            proc.wait()
    return proc
