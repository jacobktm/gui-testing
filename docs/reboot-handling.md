# Reboot Handling

The framework supports tests that require rebooting the system (e.g., graphics mode changes). This is handled through autologin configuration, resume mechanisms, and state persistence.

## Overview

Reboot tests:
1. Run setup before reboot (autologin, resume unit)
2. Execute test that triggers reboot
3. After reboot, autologin logs in
4. Resume unit continues pytest from where it left off
5. Cleanup restores original state

## Components

### harness/reboot/

- `autostart.py` - Autostart/resume unit management
- `session.py` - Session handling
- `system.py` - System reboot operations
- `resume.py` - Resume logic
- `__main__.py` - CLI for reboot management

### conftest.py

Handles reboot test coordination:
- Detects reboot tests during collection
- Prepares autologin/resume before tests
- Tracks completed tests across reboots
- Restores state after completion

### pytest.sh

Sets up passwordless sudo for reboot operations and manages autologin.

## How It Works

### 1. Test Collection

In `conftest.py`:
```python
# Remember which reboot tests will actually execute
config._gui_reboot_items = [
    item.nodeid
    for item in items
    if item.get_closest_marker("reboot") and not item.get_closest_marker("skip")
]
```

### 2. Setup (Before Tests)

If reboot tests are present and not resuming:
- Create passwordless sudoers rule for reboot commands
- Enable autologin via `harness.reboot enable`
- Install resume systemd user unit
- Save run directory and pytest args for resume

### 3. Test Execution

Tests marked with `@pytest.mark.reboot` run normally. When a reboot is triggered, the system reboots.

### 4. Resume After Reboot

After reboot and autologin:
- Resume unit starts pytest with `--resume-run <run_dir>` and `GUI_TESTING_RESUMED=1`
- `conftest.py` loads the previous run
- Tests completed before reboot are skipped (outcome overridden)
- Remaining tests execute

### 5. Cleanup

After all tests complete:
- Restore autologin settings
- Remove resume unit
- Remove passwordless sudoers rule
- Restore original graphics mode/brightness
- Trigger final reboot (optional)

## Marking Reboot Tests

```python
import pytest

class TestGraphics:
    @pytest.mark.reboot
    @pytest.mark.graphics_individual
    def test_graphics_transition(self, artifacts):
        # This test may reboot the system
        ...
```

## State Persistence

The framework persists state across reboots using:
- **Artifacts directory** - Survives reboot, contains all test data
- **Resume marker** - Tells conftest this is a resumed run
- **Completed tests tracking** - Records which tests finished before reboot
- **Power/graphics state** - `harness.power_state` saves original settings

```python
from harness import power_state
from handlers.system76_power import System76Power

# Save original state
h = System76Power()
power_state.save_original_graphics_mode_from(h)

# Restore later
power_state.restore_original_graphics_mode(h)
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GUI_TESTING_RESUME_RUN` | Path to run directory to resume |
| `GUI_TESTING_RESUMED` | Set to "1" for resumed runs |
| `GUI_TESTING_SETUP_DONE` | Set by pytest.sh after privileged setup |
| `GUI_TESTING_ARTIFACTS` | Override artifacts directory |
| `RUN_DESTRUCTIVE_TESTS` | Enable/disable destructive tests (default: 1) |

## Manual Resume

If a reboot test is interrupted:
```bash
./pytest.sh --resume-run artifacts/2024-01-01_12-00-00
```

Or set environment variable:
```bash
GUI_TESTING_RESUME_RUN=artifacts/2024-01-01_12-00-00 ./pytest.sh
```

## Troubleshooting

### Autologin not working
- Check display manager configuration (gdm3, greetd, etc.)
- Verify user permissions
- Check `harness.reboot` logs

### Resume not triggering
- Ensure resume unit is installed
- Check systemd user services
- Verify run directory path

### Tests re-running after reboot
- Check `GUI_TESTING_RESUMED` is set
- Verify completed tests are recorded
- Check artifacts directory is accessible

### Cleanup issues
- Sudoers rule may not be removed if interrupted
- Manually run: `sudo python3 -m harness.reboot cleanup`
- Restore autologin: `sudo python3 -m harness.reboot restore`
