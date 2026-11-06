"""Privileged primitives for reboot-aware runs.

``pytest.sh`` installs a deliberately narrow sudoers rule that whitelists
exactly one command: the root-owned wrapper script at :data:`HELPER_PATH`.  That
wrapper ``cd``s to a root-owned snapshot of this package and execs the package's
reboot CLI, so the passwordless-sudo grant can never be steered toward
user-writable code.

Why not grant ``python3 -m harness.reboot <subcmd>`` directly?  ``sudo`` keeps
the caller's working directory and ``python3 -m`` puts that directory on
``sys.path``, so ``cd /tmp/evil && sudo -n python3 -m harness.reboot status``
would execute attacker-controlled Python as root.  Likewise, granting ``tee``,
``cat`` or ``rm`` gives root-level writes/deletes to whichever paths appear in
the rule.  Both shapes are replaced here by one fixed command whose behaviour is
decided by root-owned code.

Two roles:

* client side, running as the test user: :func:`priv_read`, :func:`priv_write`,
  :func:`priv_remove`, :func:`priv_sysrq`, :func:`priv_reboot`,
  :func:`priv_reboot_graceful`, :func:`priv_cleanup`
* server side, running as root when the wrapper executes the CLI:
  :func:`dispatch` and its :func:`cmd_*` handlers

Every target path is hard-coded or allowlisted here, on purpose: the caller must
not be able to choose an arbitrary file.  The sudoers file itself is only ever
*removed* (see :func:`cmd_cleanup`), never written, so a compromised run cannot
widen its own grant.

Standard library only: the wrapper runs the system interpreter, not the project
virtualenv.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    "COSMIC_GREETER_CONFIG",
    "GDM_CONFIGS",
    "GREETD_CONFIG",
    "HELPER_PATH",
    "LIGHTDM_CONFIG",
    "SDDM_CONFIG",
    "SERVER_ACTIONS",
    "SNAPSHOT_DIR",
    "STATE_DIR",
    "SUDOERS_FILE",
    "SERVER_ACTIONS",
    "UNIT_FILE_NAME",
    "dispatch",
    "helper_available",
    "priv_cleanup_sudoers",
    "priv_cleanup_unit",
    "priv_read",
    "priv_reboot",
    "priv_reboot_graceful",
    "priv_remove",
    "priv_sysrq",
    "priv_write",
]

# Root-owned wrapper whitelisted in sudoers.  Overridable for unusual installs
# and for tests; ``pytest.sh`` exports this to the whole run.
HELPER_PATH = Path(
    os.environ.get("GUI_TESTING_PRIVILEGED_HELPER", "/usr/local/libexec/gui-testing-privileged")
)

# Root-owned copy of this package that the wrapper executes.
SNAPSHOT_DIR = Path(
    os.environ.get("GUI_TESTING_PRIVILEGED_SNAPSHOT", "/usr/local/libexec/gui-testing")
)

# Harness state directory (snapshots of display-manager configuration).
STATE_DIR = Path("/var/lib/gui-testing")

# The sudoers rule the harness installs.  Removable by ``cleanup`` only.
SUDOERS_FILE = Path("/etc/sudoers.d/gui-testing")

# Display-manager configurations the harness is allowed to edit.
COSMIC_GREETER_CONFIG = Path("/etc/greetd/cosmic-greeter.toml")
GREETD_CONFIG = Path("/etc/greetd/config.toml")
GDM_CONFIGS = (Path("/etc/gdm3/custom.conf"), Path("/etc/gdm/custom.conf"))
LIGHTDM_CONFIG = Path("/etc/lightdm/lightdm.conf")
SDDM_CONFIG = Path("/etc/sddm.conf.d/zz-gui-testing-autologin.conf")

# Name of the systemd user unit that resumes a run after a reboot.
UNIT_FILE_NAME = "gui-testing-resume.service"

# Exact paths that may be read, written or removed.  SUDOERS_FILE is excluded on
# purpose: the helper only ever deletes it.
EDITABLE_EXACT = (
    COSMIC_GREETER_CONFIG,
    GREETD_CONFIG,
    LIGHTDM_CONFIG,
    SDDM_CONFIG,
    *GDM_CONFIGS,
)

# SysRq entry points, keyed by the single character the harness writes.
SYSRQ_TARGETS = {
    "1": Path("/proc/sys/kernel/sysrq"),
    "b": Path("/proc/sysrq-trigger"),
}

# Subcommands handled here rather than by :mod:`harness.reboot.__main__`.
SERVER_ACTIONS = ("read", "write", "remove", "sysrq", "reboot", "reboot-graceful", "cleanup-unit")


# ---------------------------------------------------------------------------
# Server side (runs as root)
# ---------------------------------------------------------------------------


class HelperPathError(ValueError):
    """Raised when a requested path is not on the helper's allowlist."""


def _resolved(path_text: str) -> Path:
    """Absolute, symlink-resolved path, rejecting anything indirection-prone."""
    candidate = Path(path_text)
    if not candidate.is_absolute():
        raise HelperPathError(f"refusing relative path: {path_text!r}")
    resolved = Path(os.path.realpath(str(candidate)))
    if resolved != Path(os.path.normpath(str(candidate))):
        raise HelperPathError(f"refusing path that resolves elsewhere: {path_text!r} -> {resolved}")
    return resolved


def _is_unit_file(path: Path) -> bool:
    parts = path.parts
    if path.name != UNIT_FILE_NAME:
        return False
    if parts[0] != "/" or len(parts) < 2 or parts[1] not in ("home", "root"):
        return False
    return ".config" in parts and "systemd" in parts and "user" in parts


def guard(path_text: str, *, remove: bool = False) -> Path:
    """Return the allowlisted absolute path for ``path_text``.

    Raises :class:`HelperPathError` for anything the helper is not permitted to
    touch.  ``remove`` additionally accepts resume-unit unit files and symlinks
    under a user's ``.config/systemd/user`` tree.
    """
    resolved = _resolved(path_text)
    if resolved in EDITABLE_EXACT:
        return resolved
    if resolved.parent == STATE_DIR and resolved.name not in ("", "."):
        return resolved
    if remove and _is_unit_file(resolved):
        return resolved
    raise HelperPathError(f"path is not on the helper allowlist: {resolved}")


def cmd_read(path_text: str) -> tuple[int, str]:
    try:
        return 0, guard(path_text).read_text(encoding="utf-8")
    except HelperPathError as exc:
        return 2, f"{exc}\n"
    except OSError:
        # Missing or unreadable: the caller treats empty output as "absent".
        return 1, ""


def cmd_write(path_text: str, text: str) -> tuple[int, str]:
    try:
        destination = guard(path_text)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Write-and-rename so a reboot landing mid-write cannot truncate state.
        tmp = destination.parent / f".{destination.name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.sync()
        tmp.replace(destination)
        os.sync()
        return 0, ""
    except HelperPathError as exc:
        return 2, f"{exc}\n"
    except OSError as exc:
        return 1, f"write failed: {exc}\n"


def cmd_remove(path_text: str) -> tuple[int, str]:
    try:
        target = guard(path_text, remove=True)
    except HelperPathError as exc:
        return 2, f"{exc}\n"
    try:
        target.unlink()
        return 0, ""
    except FileNotFoundError:
        return 0, ""
    except OSError as exc:
        return 1, f"remove failed: {exc}\n"


def cmd_cleanup_unit(path_text: str) -> tuple[int, str]:
    """Remove a resume unit *and* its ``.wants`` symlink in one allowlisted call."""
    rc, message = cmd_remove(path_text)
    unit = Path(path_text)
    if unit.parent.name == "user":
        wants = unit.parent / "graphical-session.target.wants" / unit.name
        try:
            wants.unlink()
        except (FileNotFoundError, OSError):
            pass
    return rc, message


def cmd_sysrq(value: str) -> tuple[int, str]:
    target = SYSRQ_TARGETS.get(value)
    if target is None:
        return 2, f"sysrq value must be one of {sorted(SYSRQ_TARGETS)}\n"
    try:
        target.write_text(value, encoding="utf-8")
        return 0, ""
    except OSError as exc:
        return 1, f"sysrq write to {target} failed: {exc}\n"


def cmd_reboot() -> tuple[int, str]:
    """Force a reboot through the kernel reboot(2) syscall."""
    os.sync()
    sys.stdout.flush()
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        rc = libc.reboot(ctypes.c_uint(0x01234567))  # RB_AUTOBOOT
    except OSError as exc:
        return 1, f"reboot syscall unavailable: {exc}\n"
    if rc != 0:
        errno = ctypes.get_errno()
        return 1, f"reboot syscall failed: errno={errno} ({os.strerror(errno)})\n"
    # Success means the kernel is already tearing down; this process dies here.
    return 0, ""


def cmd_reboot_graceful() -> tuple[int, str]:
    """Ask systemd for an orderly reboot (services get to save state)."""
    try:
        result = subprocess.run(
            ["systemctl", "reboot"], capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"systemctl reboot failed: {exc}\n"
    return (0, "") if result.returncode == 0 else (1, (result.stderr or "").strip() + "\n")


def dispatch(action: str, args: Sequence[str], *, stdin_text: str | None = None) -> tuple[int, str]:
    """Perform one privileged primitive.  Returns ``(returncode, stdout)``."""
    if action == "read":
        return cmd_read(args[0])
    if action == "write":
        # Payload always travels on stdin, never in argv: nothing sensitive or
        # arbitrarily large ends up in the process list.
        return cmd_write(args[0], stdin_text if stdin_text is not None else sys.stdin.read())
    if action == "remove":
        return cmd_remove(args[0])
    if action == "cleanup-unit":
        return cmd_cleanup_unit(args[0])
    if action == "sysrq":
        return cmd_sysrq(args[0])
    if action == "reboot":
        return cmd_reboot()
    if action == "reboot-graceful":
        return cmd_reboot_graceful()
    return 2, f"unknown helper action: {action!r}\n"


# ---------------------------------------------------------------------------
# Client side (runs as the test user)
# ---------------------------------------------------------------------------


def helper_available() -> bool:
    return HELPER_PATH.is_file() and os.access(HELPER_PATH, os.X_OK)


def _invoke(args: Sequence[str], *, stdin_text: str | None = None, timeout: float, password: bool) -> str | None:
    """Run the wrapper through sudo (or directly when we are already root).

    Returns the helper's stdout on success, ``None`` on any failure.
    """
    if os.geteuid() == 0:
        rc, output = dispatch(args[0], args[1:], stdin_text=stdin_text)
        return output if rc == 0 else None
    cmd = (["sudo"] if password else ["sudo", "-n"]) + [str(HELPER_PATH)] + list(args)
    try:
        completed = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode == 0:
        return completed.stdout
    return None


def priv_read(path: Path | str, *, timeout: float = 20.0) -> str | None:
    result = _invoke(["read", str(path)], timeout=timeout, password=False)
    if result is None:
        # Passwordless sudo is unavailable (initial run before setup, or the
        # rule is gone): fall back to asking, which is what setup does anyway.
        result = _invoke(["read", str(path)], timeout=120.0, password=True)
    return result


def priv_write(path: Path | str, text: str, *, timeout: float = 20.0) -> bool:
    if _invoke(["write", str(path)], stdin_text=text, timeout=timeout, password=False) is None:
        return _invoke(["write", str(path)], stdin_text=text, timeout=120.0, password=True) is not None
    return True


def priv_remove(path: Path | str, *, timeout: float = 30.0) -> bool:
    if _invoke(["remove", str(path)], timeout=timeout, password=False) is None:
        return _invoke(["remove", str(path)], timeout=120.0, password=True) is not None
    return True


def priv_cleanup_unit(path: Path | str, *, timeout: float = 20.0) -> bool:
    if _invoke(["cleanup-unit", str(path)], timeout=timeout, password=False) is None:
        return _invoke(["cleanup-unit", str(path)], timeout=120.0, password=True) is not None
    return True


def priv_sysrq(value: str, *, timeout: float = 10.0) -> bool:
    return _invoke(["sysrq", value], timeout=timeout, password=False) is not None


def priv_reboot(*, timeout: float = 60.0) -> bool:
    return _invoke(["reboot"], timeout=timeout, password=False) is not None


def priv_reboot_graceful(*, timeout: float = 60.0) -> bool:
    return _invoke(["reboot-graceful"], timeout=timeout, password=False) is not None


def priv_cleanup_sudoers(*, timeout: float = 20.0) -> bool:
    """Remove the passwordless sudoers rule via the (root-owned) helper."""
    if os.geteuid() == 0:
        try:
            SUDOERS_FILE.unlink()
            return True
        except OSError:
            return False
    if not helper_available():
        return False
    # ``cleanup`` lives in the CLI so the rule removal stays next to the state
    # it belongs to; the wrapper runs as root, so it can unlink the file itself.
    try:
        completed = subprocess.run(
            ["sudo", "-n", str(HELPER_PATH), "cleanup"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
