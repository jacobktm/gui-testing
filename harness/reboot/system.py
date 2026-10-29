"""System-level reboot orchestration (handler-agnostic).

Rebooting the machine and waiting for it to come back are generic workflow
concerns: nothing here knows about any specific handler.  Callers only pass an
artifact ``run_dir`` so a persistent marker can survive the reboot.

Reboot strategy — no long command chains::

    1. ``sudo -n python3 -m harness.reboot reboot``  → kernel reboot(2) syscall
       via ctypes.  The sudoers rule installed by pytest.sh whitelists
       ``python3 -m harness.reboot *``, so no extra configuration is needed.
       This either reboots the kernel immediately or returns an error —
       no polkit, no inhibitor locks, no silent failure.
    2. ``sudo -n reboot -f``                         → force reboot fallback.
    3. SysRq ``b``                                   → last resort.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

EPHEMERAL_MARKER = Path("/tmp/gui-testing-reboot-marker")


def setup_autologin(username: str | None = None) -> bool:
    """Enable autologin for the detected GUI user (generic, no handler).

    Skips if pytest.sh already set up autologin (GUI_TESTING_SETUP_DONE=1)
    or if autologin is already enabled (e.g., a resumed run).
    """
    if os.environ.get("GUI_TESTING_SETUP_DONE") == "1":
        print("  [setup_autologin] already done by pytest.sh, skipping", flush=True)
        return True
    try:
        from .session import COSMIC_GREETER_CONFIG, GREETD_CONFIG, _read_privileged

        for cfg in (COSMIC_GREETER_CONFIG, GREETD_CONFIG):
            if cfg.exists():
                text = _read_privileged(cfg)
                if text and "[initial_session]" in text:
                    print("  [setup_autologin] autologin already enabled, skipping", flush=True)
                    return True
    except Exception:
        pass
    try:
        from . import AutologinManager

        result = AutologinManager().enable(username=username)
        print(f"  [setup_autologin] enabled={result.enabled} reason={result.reason}", flush=True)
        return result.enabled
    except Exception as e:
        print(f"  [setup_autologin] exception: {e}", flush=True)
        return False


def _run(cmd: list[str], timeout: float = 30.0):
    print(f"  $ {' '.join(cmd)}", flush=True)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"    exception: {e}", flush=True)
        return None


def _prepare_markers(run_dir: Path | None) -> dict:
    """Record boot ID and create persistent + ephemeral reboot markers."""
    state: dict = {"boot_id_before": None, "persistent_marker": None}
    try:
        state["boot_id_before"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except Exception:
        pass

    if run_dir is not None:
        try:
            pm = Path(run_dir) / "reboot-marker"
            pm.write_text("reboot_pending", encoding="utf-8")
            state["persistent_marker"] = pm
        except Exception:
            pass
    try:
        EPHEMERAL_MARKER.write_text("reboot_pending", encoding="utf-8")
    except Exception:
        pass
    return state


# Commands for a GRACEFUL reboot (systemd shutdown runs; services may save
# state — required when the test semantics depend on a normal shutdown, e.g.
# the brightness-preserved-across-reboot check).
GRACEFUL_REBOOT_CMDS = [
    ["systemctl", "reboot"],                # polkit (no sudo)
    ["sudo", "-n", "systemctl", "reboot"],  # sudo (sudoers whitelisted)
    ["sudo", "-n", "reboot", "-f"],         # force fallback
]

# Reliable chain for graphics transitions (matches previous working behavior).
# systemd polkit/sudo paths are more likely to actually trigger a reboot on
# this system than the raw reboot(2) syscall.
RELIABLE_REBOOT_CMDS = [
    ["sudo", "-n", "reboot", "-f"],
    ["sudo", "-n", "systemctl", "reboot"],
    ["systemctl", "reboot", "--force"],
    ["reboot", "-f"],
    ["reboot"],
    ["systemctl", "reboot"],
]


def reboot(run_dir: Path | None = None, graceful: bool = False) -> bool:
    """Reboot the system.

    Never returns normally if a reboot command succeeds — the kernel kills
    the process.  Returns only when every method failed.

    ``graceful=True`` uses a normal systemd shutdown instead of an abrupt
    reboot.  Use it when the test outcome depends on services receiving a
    proper shutdown sequence (e.g. brightness preservation).
    """
    state = _prepare_markers(run_dir)

    if graceful:
        for cmd in GRACEFUL_REBOOT_CMDS:
            print(f"  Trying graceful reboot: {' '.join(cmd)}", flush=True)
            result = _run(cmd)
            stderr = (result.stderr.strip() if result else "")
            print(f"    rc={result.returncode if result else None} stderr={stderr!r}", flush=True)
            print("  Waiting 5s to see if reboot happens...", flush=True)
            time.sleep(5)
            if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != state["boot_id_before"]:
                return True
            print("  Reboot not confirmed; trying next method...", flush=True)
        print("  No graceful method confirmed; falling back to other methods", flush=True)
    else:
        for cmd in RELIABLE_REBOOT_CMDS:
            print(f"  Trying reboot: {' '.join(cmd)}", flush=True)
            result = _run(cmd)
            stderr = (result.stderr.strip() if result else "")
            print(f"    rc={result.returncode if result else None} stderr={stderr!r}", flush=True)
            print("  Waiting 5s to see if reboot happens...", flush=True)
            time.sleep(5)
            if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != state["boot_id_before"]:
                return True
            print("  Reboot not confirmed; trying next method...", flush=True)
        print("  No standard method confirmed; trying kernel reboot(2) syscall", flush=True)

    # Pre-flight: enable SysRq so the last-resort method works.
    _run(["sh", "-c", "echo 1 | sudo tee /proc/sys/kernel/sysrq > /dev/null"], timeout=5)
    _run(["sync"], timeout=10)
    print("  Rebooting via kernel reboot(2) syscall (sudo harness.reboot reboot)...", flush=True)
    result = _run(["sudo", "-n", "python3", "-m", "harness.reboot", "reboot"])
    stderr = (result.stderr.strip() if result else "")
    print(f"    rc={result.returncode if result else None} stderr={stderr!r}", flush=True)

    print("  Waiting 5s to see if reboot happens...", flush=True)
    time.sleep(5)

    boot_id = lambda: Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if boot_id() == state["boot_id_before"]:
        # Still here → syscall failed. Force reboot next.
        print("  Reboot not confirmed; trying sudo reboot -f...", flush=True)
        result = _run(["sudo", "-n", "reboot", "-f"])
        print(f"    rc={result.returncode if result else None} stderr={(result.stderr.strip() if result else '')!r}", flush=True)
        time.sleep(5)
        if boot_id() == state["boot_id_before"]:
            print("  Reboot not confirmed; forcing via SysRq...", flush=True)
            _run(["sh", "-c", "echo b | sudo tee /proc/sysrq-trigger > /dev/null"], timeout=10)
    return True


def wait_for_boot(run_dir: Path | None = None, timeout: float = 600.0) -> bool:
    """Wait for the system to be up and running after a reboot."""
    print("Waiting for system to reboot...", flush=True)
    time.sleep(5)
    deadline = time.time() + timeout
    elapsed = 0
    persistent_prefix = Path(run_dir) / "reboot-marker" if run_dir is not None else None
    boot_id_before = None
    if persistent_prefix is not None and persistent_prefix.exists():
        # Rebooting was pending for this run directory; markers prove reboot.
        pass

    while time.time() < deadline:
        rebooted = False
        # Persistent marker exists + ephemeral gone => reboot happened.
        p_exists = persistent_prefix is not None and persistent_prefix.exists()
        e_exists = Path(EPHEMERAL_MARKER).exists()
        if p_exists and not e_exists:
            rebooted = True
        if rebooted:
            print("  Reboot confirmed", flush=True)

        try:
            result = _run(["systemctl", "is-system-running"], timeout=10)
            status = (result.stdout.strip() if result else "")
            rc = result.returncode if result else None
            if status in ("running", "degraded") or (rc == 0 and status):
                if not rebooted:
                    print("  Warning: reboot markers unchanged, system may not have rebooted", flush=True)
                else:
                    print(f"  System rebooted and is {status} (after {elapsed}s)", flush=True)
                # Settle: give the system time to fully initialize.
                print("  Settling for 10s...", flush=True)
                time.sleep(10)
                for m in (persistent_prefix, EPHEMERAL_MARKER):
                    try:
                        if m is not None and Path(m).exists():
                            Path(m).unlink()
                    except Exception:
                        pass
                return True
            if status:
                print(f"  ... {status} ({elapsed}s)", flush=True, end="\r")
        except Exception:
            pass
        time.sleep(5)
        elapsed += 5
    print(f"  Timed out after {timeout}s", flush=True)
    return False


def did_reboot(run_dir: Path | None = None) -> bool:
    """Check whether a reboot occurred for the given run directory."""
    persistent = Path(run_dir) / "reboot-marker" if run_dir is not None else None
    if persistent is not None and persistent.exists() and not Path(EPHEMERAL_MARKER).exists():
        return True
    return False
