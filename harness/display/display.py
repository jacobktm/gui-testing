import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib

__all__ = [
    "get_display",
    "get_display_index",
    "get_monitors",
    "monitor_index_for_geometry",
]


def _monitor_geometry(monitor):
    geom = monitor.get_geometry()
    return {
        "x": geom.x,
        "y": geom.y,
        "width": geom.width,
        "height": geom.height,
        "aspect_ratio": geom.width / geom.height,
        "scale": monitor.get_scale_factor(),
        "model": monitor.get_model() or "Unknown",
    }


def get_monitors():
    display = Gdk.Display.get_default()
    return [_monitor_geometry(display.get_monitor(i))
            for i in range(display.get_n_monitors())]


def get_display():
    geometry = {}

    def inspect():
        gdk_win = window.get_window()
        if not gdk_win:
            return True

        display = window.get_display()
        monitor = display.get_monitor_at_window(gdk_win)

        if monitor:
            geometry.update(_monitor_geometry(monitor))
            window.destroy()
            Gtk.main_quit()
            return False  # Stop GLib timeout
        return True  # Retry if compositor hasn't finished handshake

    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_decorated(False)
    window.set_default_size(10, 10)
    window.connect("realize", lambda w: GLib.timeout_add(60, inspect))
    GLib.timeout_add(250, Gtk.main_quit)
    window.show_all()
    Gtk.main()

    return geometry


def monitor_index_for_geometry(monitors, geometry):
    if not geometry:
        return None

    target = (
        geometry.get("x"),
        geometry.get("y"),
        geometry.get("width"),
        geometry.get("height"),
    )
    for index, monitor in enumerate(monitors):
        candidate = (
            monitor.get("x"),
            monitor.get("y"),
            monitor.get("width"),
            monitor.get("height"),
        )
        if candidate == target:
            return index

    x = geometry.get("x")
    y = geometry.get("y")
    width = geometry.get("width")
    height = geometry.get("height")
    if None in (x, y, width, height):
        return None
    center_x = x + width / 2
    center_y = y + height / 2
    for index, monitor in enumerate(monitors):
        if (
            monitor["x"] <= center_x < monitor["x"] + monitor["width"]
            and monitor["y"] <= center_y < monitor["y"] + monitor["height"]
        ):
            return index
    return None


def get_display_index(monitors=None):
    if monitors is None:
        monitors = get_monitors()
    return monitor_index_for_geometry(monitors, get_display())
