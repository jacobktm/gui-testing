"""Small shared helpers for the system76_power workflows."""
from __future__ import annotations


def reboot_and_wait(handler, graceful: bool = False) -> bool:
    """Reboot and wait for the system to come back (reboot-aware resume).

    Returns ``False`` when the machine never left the original boot — callers
    must treat that as a hard failure, since post-reboot verification on a
    machine that did not reboot proves nothing.
    """
    from harness.reboot.system import reboot, wait_for_boot

    run_dir = handler.artifacts.run_dir if getattr(handler, "artifacts", None) is not None else None
    if not reboot(run_dir, graceful=graceful):
        return False
    return wait_for_boot(run_dir)


def popup_reboot_and_wait(handler, wait: float = 90.0) -> bool:
    """Reboot through the Pop!_OS 22.04 post-switch modal instead of forcing it.

    Clicking a graphics mode in the GNOME extension starts an asynchronous
    mode switch; when it finishes (easily over a minute) the shell shows a
    modal whose "Reboot Now" button performs the reboot.  Forcing
    ``reboot -f`` while that switch is still in flight leaves the machine in
    a broken state — the modal cannot fire before the system says it is
    ready, which is the whole point of using this pathway.

    The button is reached without any coordinate detection: after *wait*
    seconds (≥ 90 s by default, per hardware verification) the modal's
    button order is addressed with Tab, Tab, Enter.  Boot confirmation is
    the usual marker dance — the current boot ID is recorded *before* the
    keys are sent, then :func:`wait_for_boot` confirms the machine left it,
    whoever initiated the reboot.  As with the scripted path, the reboot
    normally kills this pytest process and the resume unit continues on the
    next boot.

    Returns ``True`` when a new boot was confirmed; falls back to the
    scripted reboot path when the modal never produced one.
    """
    import time

    from harness.reboot.system import (
        mark_reboot_pending,
        setup_autologin,
        wait_for_boot,
    )

    run_dir = handler.artifacts.run_dir if getattr(handler, "artifacts", None) is not None else None
    setup_autologin()
    mark_reboot_pending(run_dir)
    print(f"  [popup_reboot] waiting {wait:.0f}s for the mode switch to finish...", flush=True)
    time.sleep(wait)
    from harness.dotool import send_keys

    print("  [popup_reboot] activating modal button: tab, tab, enter", flush=True)
    send_keys("key tab\nkey tab\nkey enter")
    if wait_for_boot(run_dir):
        return True
    print(
        "  [popup_reboot] modal did not produce a confirmed reboot; "
        "falling back to the scripted reboot",
        flush=True,
    )
    return reboot_and_wait(handler, graceful=True)
