"""Desktop-session helpers for reboot-aware test runs.

The harness reboots the machine it runs on.  A run that spans a reboot has to
bring the graphical session back without a human in the loop, which means:

* find out which desktop/display manager is in use (GNOME/gdm,
  COSMIC/cosmic-greeter, lightdm, sddm, ...);
* find out which user actually owns the graphical session (``pytest`` is often
  started through ``sudo``, so ``os.getuid()`` is not good enough);
* enable passwordless autologin for that user, remembering the previous
  configuration so it can be restored when the run is over.

Everything here is program-agnostic so any package's tests can reuse it.
System writes are best-effort: :func:`_write_privileged` tries a direct write
first and falls back to ``sudo -n tee``.
"""

from __future__ import annotations

import grp
import json
import os
import pwd
import re
import sys
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "AutologinManager",
    "AutologinResult",
    "DesktopSession",
    "detect_desktop",
    "detect_display_manager",
    "detect_gui_user",
    "detect_session",
    "render_cosmic_autologin",
    "render_gdm_autologin",
    "render_lightdm_autologin",
    "render_sddm_autologin",
    "force_restore_autologin",
    "restore_autologin",
]

#: Where the original display-manager configuration is snapshotted.  It lives
#: outside the repository so a run that reboots can still restore itself.
AUTOLOGIN_STATE = Path("/var/lib/gui-testing/autologin.json")

COSMIC_GREETER_CONFIG = Path("/etc/greetd/cosmic-greeter.toml")
GREETD_CONFIG = Path("/etc/greetd/config.toml")
GDM_CONFIGS = (Path("/etc/gdm3/custom.conf"), Path("/etc/gdm/custom.conf"))
LIGHTDM_CONFIG = Path("/etc/lightdm/lightdm.conf")
SDDM_CONFIG = Path("/etc/sddm.conf.d/zz-gui-testing-autologin.conf")

COSMIC_SESSION_COMMANDS = ("start-cosmic", "cosmic-session")
_GRAPHICAL_SESSION_TYPES = {"wayland", "x11", "mir"}


@dataclass(frozen=True)
class DesktopSession:
    """The desktop environment that owns the current graphical session."""

    desktop: str  # "gnome" | "cosmic" | "other"
    display_manager: str  # "gdm" | "cosmic-greeter" | "lightdm" | "sddm" | "unknown"
    username: str
    session_command: str | None = None


@dataclass(frozen=True)
class AutologinResult:
    enabled: bool
    desktop: str
    display_manager: str
    username: str
    path: Path | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _read_privileged(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        pass
    completed = _run(["sudo", "-n", "cat", str(path)])
    if completed is not None and completed.returncode == 0:
        return completed.stdout
    return None


def _write_privileged(path: Path, text: str) -> bool:
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True
    except (PermissionError, OSError):
        pass
    # Need root: try passwordless sudo first (works in background),
    # then fall back to interactive sudo (prompts in terminal).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        subprocess.run(["sudo", "-n", "mkdir", "-p", str(path.parent)],
                      stdout=subprocess.DEVNULL, stderr=None)
    # Try passwordless first.
    try:
        result = subprocess.run(
            ["sudo", "-n", "tee", str(path)],
            input=text,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    # Fall back to interactive sudo.
    try:
        result = subprocess.run(
            ["sudo", "tee", str(path)],
            input=text,
            stdout=subprocess.DEVNULL,
            stderr=None,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _remove_privileged(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except (PermissionError, OSError):
        pass
    # Try passwordless first.
    try:
        result = subprocess.run(
            ["sudo", "-n", "rm", "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        if result.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    # Fall back to interactive.
    try:
        result = subprocess.run(
            ["sudo", "rm", "-f", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=None,
            timeout=60,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _is_active(unit: str) -> bool:
    completed = _run(["systemctl", "is-active", unit])
    return completed is not None and completed.returncode == 0 and completed.stdout.strip() == "active"


def _display_manager_from_unit() -> str | None:
    completed = _run(["systemctl", "show", "display-manager", "--property=Id", "--value"])
    if completed is None or completed.returncode != 0:
        return None
    unit = completed.stdout.strip().lower()
    if "cosmic-greeter" in unit:
        return "cosmic-greeter"
    if "gdm" in unit:
        return "gdm"
    if "lightdm" in unit:
        return "lightdm"
    if "sddm" in unit:
        return "sddm"
    return None


def detect_display_manager() -> str:
    """Return the active display manager name, best-effort."""
    unit = _display_manager_from_unit()
    if unit:
        return unit
    if COSMIC_GREETER_CONFIG.exists() and _is_active("cosmic-greeter"):
        return "cosmic-greeter"
    for unit_name, name in (
        ("gdm", "gdm"),
        ("gdm3", "gdm"),
        ("lightdm", "lightdm"),
        ("sddm", "sddm"),
        ("cosmic-greeter", "cosmic-greeter"),
        ("greetd", "cosmic-greeter"),
    ):
        if _is_active(unit_name):
            return name
    return "unknown"


def detect_desktop(display_manager: str | None = None, *, environ: Mapping[str, str] | None = None) -> str:
    """Return ``"gnome"``, ``"cosmic"`` or ``"other"`` for the current session."""
    env = environ if environ is not None else os.environ
    joined = " ".join(
        env.get(key, "")
        for key in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION")
    ).lower()
    if "cosmic" in joined:
        return "cosmic"
    if "gnome" in joined or "ubuntu" in joined or "pop" in joined:
        return "gnome"

    dm = display_manager if display_manager is not None else detect_display_manager()
    if dm == "cosmic-greeter":
        return "cosmic"
    if dm == "gdm":
        return "gnome"
    if Path("/usr/share/wayland-sessions/cosmic.desktop").exists() or shutil.which("cosmic-session"):
        return "cosmic"
    if Path("/usr/share/xsessions/gnome.desktop").exists() or Path("/usr/share/wayland-sessions/gnome.desktop").exists():
        return "gnome"
    return "other"


def _session_command() -> str | None:
    for command in COSMIC_SESSION_COMMANDS:
        if shutil.which(command):
            return command
    return None


def _logind_sessions() -> list[dict[str, str]]:
    completed = _run(["loginctl", "list-sessions", "--no-legend"])
    if completed is None or completed.returncode != 0:
        return []
    sessions: list[dict[str, str]] = []
    for line in completed.stdout.splitlines():
        session_id = line.split()[0] if line.split() else ""
        if not session_id:
            continue
        properties = _run(
            [
                "loginctl",
                "show-session",
                session_id,
                "--property=User,Name,Type,Class,State,Remote,Active",
            ]
        )
        if properties is None or properties.returncode != 0:
            continue
        entry: dict[str, str] = {"Id": session_id}
        for row in properties.stdout.splitlines():
            if "=" in row:
                key, value = row.split("=", 1)
                entry[key.strip()] = value.strip()
        sessions.append(entry)
    return sessions


def _runtime_socket_owner() -> str | None:
    for runtime_dir in sorted(Path("/run/user").glob("*")):
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        if not (runtime_dir / "wayland-0").exists() and not (runtime_dir / "bus").exists():
            continue
        try:
            return pwd.getpwuid(runtime_dir.stat().st_uid).pw_name
        except (KeyError, OSError):
            continue
    return None


def detect_gui_user(*, environ: Mapping[str, str] | None = None) -> str:
    """Return the user that owns the graphical session.

    ``pytest`` is frequently started through ``sudo``; in that case
    ``os.getuid()`` is ``0`` and the wrong user would be configured for
    autologin.  This looks at the actual UI session first.
    """
    env = environ if environ is not None else os.environ

    session_id = env.get("XDG_SESSION_ID")
    sessions = _logind_sessions()
    graphical = [
        entry
        for entry in sessions
        if entry.get("Class", "user") == "user"
        and entry.get("Remote", "no") != "yes"
        and entry.get("Type") in _GRAPHICAL_SESSION_TYPES
        and entry.get("State", "active") in {"active", ""}
    ]
    if session_id:
        graphical.sort(key=lambda entry: entry.get("Id") != session_id)
    for entry in graphical:
        name = entry.get("Name")
        if name and name != "root":
            return name

    owner = _runtime_socket_owner()
    if owner and owner != "root":
        return owner

    user = env.get("USER")
    if user and user != "root":
        return user

    try:
        name = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        name = "root"
    return name


def detect_session(username: str | None = None, *, environ: Mapping[str, str] | None = None) -> DesktopSession:
    """Detect desktop, display manager, GUI user and COSMIC session command."""
    display_manager = detect_display_manager()
    desktop = detect_desktop(display_manager, environ=environ)
    return DesktopSession(
        desktop=desktop,
        display_manager=display_manager,
        username=username or detect_gui_user(environ=environ),
        session_command=_session_command() if desktop == "cosmic" else None,
    )


# ---------------------------------------------------------------------------
# Config rendering (pure functions, unit-testable)
# ---------------------------------------------------------------------------


_TOML_HEADER = re.compile(r"^\s*\[([^\]]+)\]\s*(?:#.*)?$")


def strip_toml_section(text: str, section: str) -> str:
    """Remove a TOML section (and its keys) from ``text``."""
    lines = text.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        match = _TOML_HEADER.match(line)
        if match:
            skipping = match.group(1).strip() == section
            if skipping:
                continue
        if skipping:
            continue
        output.append(line)
    while output and not output[-1].strip():
        output.pop()
    return "\n".join(output)


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_cosmic_autologin(existing: str, username: str, command: str = "start-cosmic") -> str:
    """Return a greetd/cosmic-greeter config with ``[initial_session]`` set.

    Works for both ``/etc/greetd/cosmic-greeter.toml`` and a plain greetd
    ``config.toml``; the previous ``[initial_session]`` block, if any, is
    replaced so repeated preparation stays idempotent.
    """
    base = strip_toml_section(existing or "", "initial_session").rstrip()
    session = (
        "[initial_session]\n"
        f"command = {_toml_string(command)}\n"
        f"user = {_toml_string(username)}\n"
    )
    return f"{base}\n\n{session}" if base else session


def _set_ini_section_keys(text: str, section: str, updates: dict[str, str]) -> str:
    """Set keys in an INI-style section, preserving unrelated content."""
    lines = (text or "").splitlines()
    header = f"[{section}]"
    start = next(
        (index for index, line in enumerate(lines) if line.strip().lower() == header.lower()),
        None,
    )
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.append(header)
        lines.extend(f"{key}={value}" for key, value in updates.items())
        return "\n".join(lines) + "\n"

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _TOML_HEADER.match(lines[index]):
            end = index
            break

    remaining = dict(updates)
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if "=" in stripped and not stripped.startswith(("#", ";")):
            key = stripped.split("=", 1)[0].strip()
            for wanted in list(remaining):
                if wanted.lower() == key.lower():
                    lines[index] = f"{wanted}={remaining.pop(wanted)}"

    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    for key, value in remaining.items():
        lines.insert(insert_at, f"{key}={value}")
        insert_at += 1
    return "\n".join(lines) + "\n"


def render_gdm_autologin(existing: str, username: str) -> str:
    """Return a gdm3 ``custom.conf`` with automatic login enabled."""
    return _set_ini_section_keys(
        existing,
        "daemon",
        {"AutomaticLoginEnable": "true", "AutomaticLogin": username},
    )


def render_lightdm_autologin(existing: str, username: str) -> str:
    """Return a lightdm config with autologin for ``username``."""
    return _set_ini_section_keys(
        existing,
        "Seat:*",
        {"autologin-user": username, "autologin-user-timeout": "0"},
    )


def render_sddm_autologin(existing: str, username: str) -> str:
    """Return an sddm config with autologin for ``username``."""
    return _set_ini_section_keys(
        existing,
        "Autologin",
        {"User": username, "Session": "cosmic"},
    )


# ---------------------------------------------------------------------------
# Autologin management
# ---------------------------------------------------------------------------


def _state_manifest(state_path: Path) -> dict[str, Any]:
    text = _read_privileged(state_path)
    if not text:
        return {"entries": []}
    try:
        loaded = json.loads(text)
    except (TypeError, ValueError):
        return {"entries": []}
    if not isinstance(loaded, dict) or not isinstance(loaded.get("entries"), list):
        return {"entries": []}
    return loaded


class AutologinManager:
    """Temporarily enable autologin and restore the original configuration."""

    def __init__(
        self,
        session: DesktopSession | None = None,
        *,
        state_path: Path | str = AUTOLOGIN_STATE,
    ) -> None:
        self._session = session
        self.state_path = Path(state_path)

    @property
    def session(self) -> DesktopSession:
        if self._session is None:
            self._session = detect_session()
        return self._session

    def _target(self, username: str) -> tuple[Path, str] | None:
        session = self.session
        if session.desktop == "cosmic" or session.display_manager == "cosmic-greeter":
            config = COSMIC_GREETER_CONFIG if COSMIC_GREETER_CONFIG.exists() else GREETD_CONFIG
            command = session.session_command or "start-cosmic"
            return config, render_cosmic_autologin(_read_privileged(config) or "", username, command)
        if session.desktop == "gnome" or session.display_manager == "gdm":
            config = next((path for path in GDM_CONFIGS if path.exists()), GDM_CONFIGS[0])
            return config, render_gdm_autologin(_read_privileged(config) or "", username)
        if session.display_manager == "lightdm":
            return LIGHTDM_CONFIG, render_lightdm_autologin(_read_privileged(LIGHTDM_CONFIG) or "", username)
        if session.display_manager == "sddm":
            return SDDM_CONFIG, render_sddm_autologin(_read_privileged(SDDM_CONFIG) or "", username)
        return None

    def _remember(self, path: Path, existed: bool, content: str | None) -> None:
        state = _state_manifest(self.state_path)
        entries = state.setdefault("entries", [])
        if any(entry.get("path") == str(path) for entry in entries):
            return
        entries.append({"path": str(path), "existed": existed, "content": content})
        _write_privileged(self.state_path, json.dumps(state, indent=2) + "\n")

    def enable(self, username: str | None = None) -> AutologinResult:
        """Enable autologin for the GUI user.  Safe to call repeatedly."""
        session = self.session
        user = username or session.username
        target = self._target(user)
        if target is None:
            return AutologinResult(
                False,
                session.desktop,
                session.display_manager,
                user,
                reason="no supported display manager detected",
            )
        path, content = target
        # Never overwrite a file we could not read: the previous configuration
        # must be restorable, otherwise autologin would be left enabled.
        existed = path.exists()
        original = _read_privileged(path)
        if existed and original is None:
            return AutologinResult(
                False,
                session.desktop,
                session.display_manager,
                user,
                path,
                reason=f"cannot read {path}; refusing to modify it",
            )
        self._remember(path, existed, original)
        if not _write_privileged(path, content):
            return AutologinResult(
                False,
                session.desktop,
                session.display_manager,
                user,
                path,
                reason=f"could not write {path}",
            )
        return AutologinResult(True, session.desktop, session.display_manager, user, path)

    def restore(self) -> bool:
        """Restore every autologin file touched by :meth:`enable`."""
        state = _state_manifest(self.state_path)
        entries = state.get("entries") or []
        if not entries:
            return True
        ok = True
        for entry in entries:
            path = Path(str(entry.get("path", "")))
            if not str(path):
                continue
            if entry.get("existed"):
                content = entry.get("content")
                if content is None:
                    # We never recorded the original bytes; do not truncate.
                    ok = False
                    continue
                ok = _write_privileged(path, str(content)) and ok
            else:
                ok = _remove_privileged(path) and ok
        if ok:
            _remove_privileged(self.state_path)
        return ok


def force_restore_autologin() -> bool:
    """Aggressively restore autologin config without relying on state file.

    Removes [initial_session] from greetd configs and AutomaticLogin from
    gdm configs.  Used when the state file is missing or restore failed.
    """
    import sys
    ok = True
    # COSMIC / greetd
    for config_path in (COSMIC_GREETER_CONFIG, GREETD_CONFIG):
        if config_path.exists():
            text = _read_privileged(config_path)
            print(f"[force_restore] {config_path}: exists, has_initial_session={'[initial_session]' in (text or '')}", file=sys.stderr, flush=True)
            if text is not None and "[initial_session]" in text:
                cleaned = strip_toml_section(text, "initial_session").rstrip() + "\n"
                written = _write_privileged(config_path, cleaned)
                if not written:
                    # Fallback: use sudo sed to remove the section.
                    try:
                        import subprocess
                        # Use python to do the removal via sudo.
                        script = (
                            "import re, pathlib, sys\n"
                            "p = pathlib.Path(%r)\n"
                            "t = p.read_text()\n"
                            "lines = t.splitlines()\n"
                            "out = []\n"
                            "skip = False\n"
                            "for line in lines:\n"
                            "    if line.strip() == '[initial_session]':\n"
                            "        skip = True\n"
                            "        continue\n"
                            "    if skip and line.strip().startswith('['):\n"
                            "        skip = False\n"
                            "    if not skip:\n"
                            "        out.append(line)\n"
                            "p.write_text('\\n'.join(out) + '\\n')\n"
                        ) % str(config_path)
                        r = subprocess.run(
                            ["sudo", "-n", "python3", "-c", script],
                            capture_output=True, text=True, timeout=10,
                        )
                        if r.returncode == 0:
                            written = True
                            print(f"[force_restore] sudo python3 cleaned {config_path}", file=sys.stderr, flush=True)
                        else:
                            print(f"[force_restore] sudo python3 failed: {r.stderr.strip()}", file=sys.stderr, flush=True)
                    except Exception as e:
                        print(f"[force_restore] sudo fallback exception: {e}", file=sys.stderr, flush=True)
                if not written:
                    ok = False
                    print(f"[force_restore] FAILED to write {config_path}", file=sys.stderr, flush=True)
                else:
                    print(f"[force_restore] cleaned {config_path}", file=sys.stderr, flush=True)
    # GNOME / gdm
    for config_path in GDM_CONFIGS:
        if config_path.exists():
            text = _read_privileged(config_path)
            if text is not None and "AutomaticLogin" in text:
                cleaned = _set_ini_section_keys(text, "daemon", {
                    "AutomaticLoginEnable": "false",
                })
                # Remove AutomaticLogin line
                lines = cleaned.splitlines()
                lines = [l for l in lines if not l.strip().startswith("AutomaticLogin=")]
                cleaned = "\n".join(lines) + "\n"
                if not _write_privileged(config_path, cleaned):
                    ok = False
    return ok


def restore_autologin(*, state_path: Path | str | None = None) -> bool:
    """Restore autologin config from any available state file.

    Tries the default system path and the user-level path.
    """
    paths_to_try = []
    if state_path is not None:
        paths_to_try.append(Path(state_path))
    paths_to_try.append(AUTOLOGIN_STATE)
    paths_to_try.append(Path.home() / ".local" / "share" / "gui-testing" / "autologin.json")
    seen = set()
    unique = []
    for p in paths_to_try:
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)

    restored_any = False
    found_any = False
    for p in unique:
        if p.exists():
            found_any = True
            if AutologinManager(state_path=p).restore():
                restored_any = True
    if not found_any:
        return True
    return restored_any

