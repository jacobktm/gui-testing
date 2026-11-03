"""OS/platform detection and flavor registry.

This module provides a plugin-like system for OS-specific behavior.
Instead of branching on os_id strings throughout the codebase, flavors
register their capabilities and are selected based on detection.
"""

from __future__ import annotations

from .base import PlatformFlavor, PlatformInfo
from .registry import get_flavor, get_flavor_for_os_id, register_flavor, list_flavors, detect_platform

# Import flavors to trigger registration
from . import popos  # noqa
from . import ubuntu26  # noqa

__all__ = [
    "PlatformFlavor",
    "PlatformInfo",
    "get_flavor",
    "get_flavor_for_os_id",
    "register_flavor",
    "list_flavors",
    "detect_platform",
]
