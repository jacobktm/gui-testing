"""System-level reboot orchestration (handler-agnostic).

Rebooting the machine and waiting for it to come back are generic workflow
concerns: nothing here knows about any specific handler.  Callers only pass an
artifact ``run_dir`` so a persistent marker can survive the reboot.

Reboot strategy — no long command chains::

    1. ``systemctl reboot``                          → polkit, no sudo needed
       inside a graphical session (and always works when pytest is root).
    2. ``sudo -n <privileged helper> reboot``        → kernel reboot(2) syscall
       performed by the root-owned helper installed by ``pytest.sh``.  The
       sudoers rule grants that one fixed command only, so nothing user-writable
       is ever executed as root (see :mod:`harness.reboot.helper`).
    3. ``sudo -n <privileged helper> reboot-graceful`` → orderly shutdown as root.
    4. SysRq ``b``                                    → last resort, also via the
       helper.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from harness.artifacts.manifest import durable_write_text

from .helper import HELPER_PATH, priv_sysrq

EPHEMERAL_MARKER = Path("/tmp/gui-testing-reboot-marker")
BOOT_ID_NAME = "boot-id"


def _current_boot_id() -> str | None:
    """Read the current boot ID, or ``None`` if it cannot be read."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except Exception:
        return None


def _boot_id_state_path() -> Path:
    from .recovery import state_dir

    return state_dir() / BOOT_ID_NAME


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
    """Record boot ID and create persistent + ephemeral reboot markers.

    The boot ID is stored three ways so post-reboot confirmation survives the
    abrupt ``reboot(2)`` that follows moments later:

    * in the marker files themselves (persistent one lives in the run dir),
    * in ``~/.local/share/gui-testing/boot-id`` so ``wait_for_boot(None)``
      (no run dir, e.g. the end-of-session reboot) can confirm too,
    * in the in-process ``state`` dict for the per-method checks below.

    All writes are durable (fsync) so they are on disk before the reboot.
    """
    state: dict = {"boot_id_before": _current_boot_id(), "persistent_marker": None}
    boot_id_before = state["boot_id_before"] or "reboot_pending"

    if run_dir is not None:
        try:
            pm = Path(run_dir) / "reboot-marker"
            durable_write_text(pm, boot_id_before)
            state["persistent_marker"] = pm
        except Exception:
            pass
    try:
        durable_write_text(EPHEMERAL_MARKER, boot_id_before)
    except Exception:
        pass
    if state["boot_id_before"] is not None:
        try:
            path = _boot_id_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            durable_write_text(path, state["boot_id_before"])
        except Exception:
            pass
    return state


# Commands for a GRACEFUL reboot (systemd shutdown runs; services may save
# state — required when the test semantics depend on a normal shutdown, e.g.
# the brightness-preserved-across-reboot check).
GRACEFUL_REBOOT_CMDS = [
    ["systemctl", "reboot"],                            # polkit (no sudo)
    ["sudo", "-n", str(HELPER_PATH), "reboot-graceful"],  # orderly shutdown as root
    ["sudo", "-n", str(HELPER_PATH), "reboot"],           # force fallback
]

# Reliable chain for graphics transitions (matches previous working behavior).
# The kernel reboot(2) syscall through the privileged helper is the most
# dependable; polkit and unprivileged attempts stay as lower-preference tries.
RELIABLE_REBOOT_CMDS = [
    ["sudo", "-n", str(HELPER_PATH), "reboot"],            # kernel reboot(2)
    ["sudo", "-n", str(HELPER_PATH), "reboot-graceful"],   # orderly, as root
    ["systemctl", "reboot", "--force"],
    ["reboot", "-f"],
    ["reboot"],
    ["systemctl", "reboot"],
]


def mark_reboot_pending(run_dir: Path | None = None) -> dict:
    """Record the current boot ID as the pre-reboot marker *without* rebooting.

    For reboots the harness *waits for* rather than issues — e.g. the
    Pop!_OS 22.04 shell modal that appears after a GUI graphics-mode switch
    — so :func:`wait_for_boot` / :func:`did_reboot` can still confirm the
    machine left this boot.  Call this before triggering the external
    reboot.
    """
    return _prepare_markers(run_dir)


def reboot(run_dir: Path | None = None, graceful: bool = False) -> bool:
    """Reboot the system.

    Never returns normally if a reboot command succeeds — the kernel kills
    the process.  Returns only when every method failed.

    ``graceful=True`` uses a normal systemd shutdown instead of an abrupt
    reboot.  Use it when the test outcome depends on services receiving a
    proper shutdown sequence (e.g. brightness preservation).

    Returns ``True`` only when a boot-ID change confirmed the reboot; returns
    ``False`` when every method failed and we are still on the same boot.
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
            if _current_boot_id() != state["boot_id_before"]:
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
            if _current_boot_id() != state["boot_id_before"]:
                return True
            print("  Reboot not confirmed; trying next method...", flush=True)
        print("  No standard method confirmed; trying kernel reboot(2) syscall", flush=True)

    # Pre-flight: enable SysRq so the last-resort method works, and flush state
    # to disk before an abrupt reboot.
    priv_sysrq("1")
    _run(["sync"], timeout=10)
    print("  Rebooting via kernel reboot(2) syscall (privileged helper)...", flush=True)
    result = _run(["sudo", "-n", str(HELPER_PATH), "reboot"])
    stderr = (result.stderr.strip() if result else "")
    print(f"    rc={result.returncode if result else None} stderr={stderr!r}", flush=True)

    print("  Waiting 5s to see if reboot happens...", flush=True)
    time.sleep(5)

    if _current_boot_id() == state["boot_id_before"]:
        # Still here → the syscall did not take.  Ask systemd for an orderly
        # reboot as root before resorting to SysRq.
        print("  Reboot not confirmed; trying orderly reboot as root...", flush=True)
        result = _run(["sudo", "-n", str(HELPER_PATH), "reboot-graceful"])
        print(f"    rc={result.returncode if result else None} stderr={(result.stderr.strip() if result else '')!r}", flush=True)
        time.sleep(5)
        if _current_boot_id() == state["boot_id_before"]:
            print("  Reboot not confirmed; forcing via SysRq...", flush=True)
            priv_sysrq("b")
            time.sleep(5)
            if _current_boot_id() != state["boot_id_before"]:
                return True
    # If SysRq b worked we never get here; reaching the end means the boot ID
    # never changed, so honestly report that the machine did not reboot.
    print("  WARNING: every reboot method failed; the system did NOT reboot", flush=True)
    return False


def wait_for_boot(run_dir: Path | None = None, timeout: float = 600.0) -> bool:
    """Wait for the system to come back *from a different boot*.

    Returns ``True`` only when the new boot is confirmed — either the current
    boot ID differs from the one recorded by :func:`reboot` (read from the
    persistent marker or the ``boot-id`` state file), or the legacy marker
    signature holds (persistent marker present, ephemeral /tmp marker gone).

    If the system is up but the boot cannot be confirmed, returns ``False``
    with a loud warning instead of credulously declaring success: callers
    gate post-reboot verification on this, and a machine that never rebooted
    must not get to "verify" its way to a passing transition test.
    """
    print("Waiting for system to reboot...", flush=True)
    time.sleep(5)
    deadline = time.time() + timeout
    elapsed = 0
    persistent_prefix = Path(run_dir) / "reboot-marker" if run_dir is not None else None

    # Boot ID recorded before the reboot, from whichever source is available.
    boot_id_before = None
    for source in (persistent_prefix, _boot_id_state_path()):
        try:
            if source is not None and source.exists():
                value = source.read_text(encoding="utf-8").strip()
                if value and value != "reboot_pending":
                    boot_id_before = value
                    break
        except Exception:
            pass

    while time.time() < deadline:
        # Primary confirmation: the boot ID changed.
        rebooted = boot_id_before is not None and _current_boot_id() not in (None, boot_id_before)
        # Legacy confirmation: persistent marker survived, ephemeral did not.
        if not rebooted:
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
                    print(
                        "  ERROR: system is up but on the SAME boot as before — "
                        "the reboot never happened",
                        flush=True,
                    )
                    return False
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
    """Check whether a reboot occurred since the last :func:`reboot` call."""
    persistent = Path(run_dir) / "reboot-marker" if run_dir is not None else None
    if persistent is not None and persistent.exists() and not Path(EPHEMERAL_MARKER).exists():
        return True
    # Boot-ID based confirmation works even without a run directory.
    try:
        path = _boot_id_state_path()
        if path.exists():
            before = path.read_text(encoding="utf-8").strip()
            current = _current_boot_id()
            if before and current and before != current:
                return True
    except Exception:
        pass
    return False
