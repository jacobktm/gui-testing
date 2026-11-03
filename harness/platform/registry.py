"""Flavor registry."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import PlatformFlavor, PlatformInfo

_flavors: list[type["PlatformFlavor"]] = []
_instances: dict[str, "PlatformFlavor"] = {}
_loaded = False


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Auto-discover and import all flavor modules
    import importlib
    import pkgutil
    from pathlib import Path
    pkg_path = Path(__file__).parent
    for modinfo in pkgutil.iter_modules([str(pkg_path)]):
        if not modinfo.ispkg and modinfo.name not in ("__init__", "base", "registry"):
            try:
                importlib.import_module(f"{__name__.rsplit('.', 1)[0]}.{modinfo.name}")
            except Exception:
                pass
    for subdir in pkg_path.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("_"):
            try:
                importlib.import_module(f"{__name__.rsplit('.', 1)[0]}.{subdir.name}")
            except Exception:
                pass


def register_flavor(flavor_cls: type["PlatformFlavor"]) -> type["PlatformFlavor"]:
    """Register a platform flavor class."""
    _flavors.append(flavor_cls)
    _flavors.sort(key=lambda f: getattr(f, "priority", 0), reverse=True)
    return flavor_cls


def get_flavor_for_os_id(os_id: str, info: "PlatformInfo | None" = None) -> "PlatformFlavor":
    """Get the appropriate flavor for an os_id."""
    _ensure_loaded()
    if info is None:
        info = detect_platform()
        # Override os_id if different
        if os_id != info.os_id:
            info.os_id = os_id
            # Reparse version from os_id
            _parse_version_from_os_id(info)
    
    cache_key = info.os_id
    if cache_key in _instances:
        return _instances[cache_key]
    
    from .base import PlatformFlavor
    
    for flavor_cls in _flavors:
        instance_check = flavor_cls(info)
        if hasattr(instance_check, "matches_info") and instance_check.matches_info(info):
            instance = flavor_cls(info)
            _instances[cache_key] = instance
            return instance
        elif instance_check.matches_os_id(info.os_id):
            instance = flavor_cls(info)
            _instances[cache_key] = instance
            return instance
    
    # Fallback to base flavor
    instance = PlatformFlavor(info)
    _instances[cache_key] = instance
    return instance


def get_flavor(info: "PlatformInfo | None" = None) -> "PlatformFlavor":
    """Get flavor based on detected platform or environment."""
    _ensure_loaded()
    if info is None:
        info = detect_platform()
    
    return get_flavor_for_os_id(info.os_id, info)


def _parse_version_from_os_id(info: "PlatformInfo") -> None:
    """Parse version from os_id like pop-24.04."""
    try:
        if "-" in info.os_id:
            parts = info.os_id.split("-")
            if len(parts) >= 2:
                ver = parts[-1]
                if "." in ver:
                    maj, minv = ver.split(".", 1)
                    info.major = int(maj)
                    info.minor = int(minv)
                else:
                    info.major = int(ver)
                    info.minor = 0
                info.version = ver
            family = parts[0]
            if family in ("pop", "popos"):
                info.family = "popos"
            elif family == "ubuntu":
                info.family = "ubuntu"
            else:
                info.family = family
    except Exception:
        pass


def detect_platform() -> "PlatformInfo":
    """Detect current platform."""
    from .base import PlatformInfo
    
    os_id = os.environ.get("TEST_OS_ID") or os.environ.get("OS_ID")
    os_name = None
    version = None
    codename = None
    
    # Try to detect from /etc/os-release
    try:
        with open("/etc/os-release") as f:
            data = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
        os_name = data.get("NAME", "")
        version_id = data.get("VERSION_ID", "")
        version_codename = data.get("VERSION_CODENAME", "")
        codename = version_codename or None
        
        # Map to os_id format
        if not os_id:
            name_lower = os_name.lower()
            if "pop" in name_lower:
                os_id = f"pop-{version_id}"
            elif "ubuntu" in name_lower:
                os_id = f"ubuntu-{version_id}"
            else:
                os_id = version_id or "unknown"
        if not version:
            version = version_id
    except Exception:
        if not os_id:
            os_id = "pop-24.04"  # default
        if not version:
            version = "24.04"
    
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower() or None
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower() or None
    
    info = PlatformInfo(
        os_id=os_id,
        os_name=os_name or os_id,
        version=version or "",
        codename=codename,
        desktop=desktop,
        session_type=session_type,
    )
    _parse_version_from_os_id(info)
    return info


def list_flavors() -> list[str]:
    """List registered flavor names."""
    return [getattr(f, "name", f.__name__) for f in _flavors]
