# Platform Flavor System

The platform flavor system provides a plugin-like registry for OS/desktop-specific behavior. Instead of branching on `os_id` strings throughout the codebase, flavors register themselves and are automatically selected.

## How It Works

1. Flavors inherit from `PlatformFlavor` and use `@register_flavor` decorator
2. On first use, the registry auto-discovers all flavor modules
3. When getting a flavor, it matches by `os_id` pattern, then falls back to family+version matching
4. Higher priority flavors win for exact matches

## Adding Support for a New OS Version

### Option 1: Create a version-specific flavor (for special handling)

```python
# harness/platform/popos/pop26.py
from __future__ import annotations
from ..base import PlatformFlavor
from ..registry import register_flavor

@register_flavor
class Pop26Flavor(PlatformFlavor):
    name = "popos-26.04"
    matches = ["pop-26.04"]
    priority = 20
    family = "popos"
    min_version = (26, 0)
    max_version = (26, 99)
    
    def get_open_clicks(self):
        from harness.gui import Coords
        # Custom clicks for this version
        return [(Coords.OPEN[0], Coords.OPEN[1])]
```

### Option 2: Just rely on the base family flavor (simplest)

If the new version behaves like the family base (e.g., Pop!_OS 25.04), no changes needed - it will automatically use `PopOSBaseFlavor`. Only override what's different.

### Option 3: Extend the base flavor

If behavior changes for a family going forward, update the base flavor in `harness/platform/popos/base.py` or `harness/platform/ubuntu/base.py`.

## Removing Obsolete Functionality

To remove support for an old version:
1. Delete the version-specific flavor file (e.g., `popos/pop22.py`)
2. If nothing else needs it, remove its import/export
3. The registry will no longer find it and fall back to base or other matches

## Flavor API

Flavors can override:
- `get_open_clicks()` - Clicks to open settings
- `get_coord_source()` - Source resolution for coordinates
- `get_profile_prompt()` / `get_profile_expected()` / `normalize_profile()` - Profile detection
- `get_graphics_prompt()` / `get_graphics_expected()` / `supports_graphics_switching()` - Graphics
- `get_click_delay()` / `get_wait_after_clicks()` - Timing
- `pre_open_hook()` / `post_click_hook()` - Custom hooks

## Usage

```python
from harness.platform import get_flavor, get_flavor_for_os_id

# Auto-detect current platform
flavor = get_flavor()
clicks = flavor.get_open_clicks()

# Or for specific os_id
flavor = get_flavor_for_os_id("pop-25.04")
```

## Migration

Existing code using `os_id` string checks should be migrated to use the flavor API. The flavor system is backward compatible - unknown os_ids fall back to base `PlatformFlavor`.
