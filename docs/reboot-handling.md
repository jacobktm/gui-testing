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
- `helper.py` - Privileged primitives behind the root-owned sudo wrapper
- `idle.py` - Idle blanking / screen-lock disable and restore
- `recovery.py` - Run marker + boot-time self-healing recovery unit
- `__main__.py` - CLI for reboot management

### conftest.py

Handles reboot test coordination:
- Detects reboot tests during collection
- Prepares autologin/resume before tests
- Tracks completed tests across reboots
- Disables idle blanking/locking for the run (re-applied on resumed runs)
- Restores state after completion

### pytest.sh

Sets up passwordless sudo for reboot operations, manages autologin, and disables
idle/screen locking before pytest starts.

## Idle and Screen Locking

A long GUI run would otherwise blank the display or lock the screen, which
breaks screenshot capture and click coordinates. `harness/reboot/idle.py`
disables this per desktop, using only the backend for the detected desktop:

| Desktop | Mechanism |
| --- | --- |
| GNOME (Pop!_OS 22.04, Ubuntu) | `gsettings` keys for idle delay, screen locking, idle dimming and idle suspend. Key existence is probed with `gsettings list-keys`, so an **unreachable session bus is reported as an error** instead of looking like "every key is undefined". Keys the installed GNOME genuinely does not define are skipped. Applied keys are read back and logged; the critical subset (`idle-delay`, `lock-enabled`) is verified. A `gnome-session-inhibit` process also inhibits idle for the run. |
| COSMIC (Pop!_OS 24.04+) | `cosmic-idle` config: `~/.config/cosmic/com.system76.CosmicIdle/v1/{screen_off_time,suspend_on_battery_time,suspend_on_ac_time}` set to `None` (RON) to disable the timeout, then read back. |

`disable_idle()` returns a structured report — `{backend, applied, values,
readback_ok, errors}` — and `pytest.sh`, `conftest.py` and the resume script
all print its errors plus a loud warning when protection is not active.
`tests/test_idle_guard.py` (sorted to run first by conftest) then asserts the
protection is live — `idle-delay == 0`, `lock-enabled == false` on GNOME, all
timer files `None` on COSMIC — so a run that would wander into a locked
session fails in seconds instead of ~20 minutes later inside a capture.

Original values are saved durably to `~/.local/share/gui-testing/idle_state.json`
before the first change. Saving is idempotent, so a resumed run after a reboot
re-applies the disable without overwriting the originals. The generated resume
script re-applies the protection **before pytest starts** (right after the
session socket wait), covering the gap between autologin and
`pytest_configure`. Cleanup restores the saved values, and COSMIC files that
did not exist before are deleted.

Run it manually with:

```bash
python3 -c "from harness.reboot import save_idle_state, disable_idle; save_idle_state(); print(disable_idle())"
python3 -c "from harness.reboot import restore_idle; restore_idle()"
```

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

`pytest.sh` performs the privileged setup (it asks for your sudo password once),
then `conftest.py` installs the resume unit:

- Install the root-owned privileged helper at
  `/usr/local/libexec/gui-testing-privileged`, together with a root-owned copy
  of `harness/` at `/usr/local/libexec/gui-testing`. The sudoers rule grants
  exactly three fixed commands — the helper, `/usr/bin/systemctl reboot`, and
  `/usr/bin/systemctl restart com.system76.PowerDaemon.service` — with no
  wildcards, and it is validated with `visudo -cf` *before* being installed.
  Granting `python3 -m harness.reboot` directly would be a root escalation, and
  granting `tee`/`cat`/`rm` would be arbitrary root file writes; see
  `harness/reboot/helper.py`.
- Enable autologin via the helper: `sudo -n /usr/local/libexec/gui-testing-privileged enable`
- Install resume systemd user unit
- Save run directory and pytest args for resume
- Install + enable the boot-time recovery unit (`gui-testing-recover.service`,
  see below). It re-arms on every `./pytest.sh` run.

### 3. Test Execution

Tests marked with `@pytest.mark.reboot` run normally. When a reboot is triggered, the system reboots.

### 4. Resume After Reboot

After reboot and autologin:
- Resume unit starts pytest with `--resume-run <run_dir>` and `GUI_TESTING_RESUMED=1`
- `conftest.py` loads the previous run
- Tests completed before reboot are skipped (outcome overridden)
- Remaining tests execute
- Attempts are capped (default 12 boots). On the cap the unit disables itself
  and leaves `<run_dir>/resume/GAVE_UP` behind so the give-up is visible in the
  run directory.
- `conftest.py` refreshes the run marker (`~/.local/share/gui-testing/run-active`)
  on every boot, which keeps boot-time recovery from cleaning up a live run.

### 5. Cleanup

After all tests complete:
- Restore autologin settings and remove the resume unit (`finish_reboot`,
  which keeps the sudoers grant alive because the final reboot still needs it)
- Drop the run marker, restore graphics mode/brightness, then trigger the
  final reboot; the passwordless sudoers rule is removed after the last
  reboot attempt — or by the boot-time recovery unit on the next boot if the
  reboot kills pytest first.

## Boot-Time Self-Healing

A reboot kills the pytest process that set everything up, and a crash or
Ctrl-C can leave autologin enabled, a passwordless sudo rule, and a resume
unit behind. On a throwaway test install that leaked state can make the
machine unbootable-into-a-usable-desktop, which is exactly what forces a
reinstall. The harness therefore converges the machine back to a clean state
at boot instead of trusting the test process to clean up:

- `harness/reboot/recovery.py` writes a per-user **run marker**
  (`~/.local/share/gui-testing/run-active`) at collection time and refreshes
  it on every boot of a multi-boot run.
- `pytest.sh` installs a root-owned script at
  `/usr/local/libexec/gui-testing-recover` plus a `gui-testing-recover.service`
  unit that runs at every boot. If **no** marker is fresher than 12 hours it:
  revokes `/etc/sudoers.d/gui-testing`, calls the privileged helper's
  `recover` action (restore display-manager config, delete resume units),
  deletes any leftovers by hand if the helper is gone, and disables itself.
- The unit stays enabled after a clean boot so the *next* boot re-verifies
  the machine is clean; each `./pytest.sh` run re-arms it.

Useful controls:

```bash
# While debugging a run you intend to resume — leave all setup in place:
sudo touch /var/lib/gui-testing/keep-setup

# Repair immediately (unprivileged, uses the live sudoers grant):
sudo -n /usr/local/libexec/gui-testing-privileged recover
# Or when already root, from the repo:
sudo python3 -m harness.reboot recover

# Marker age limit (minutes), read by the unit:
sudo systemctl edit gui-testing-recover.service   # set GUI_TESTING_RECOVER_MAX_AGE_MIN
```

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
- **Power/graphics state** - `handlers.system76_power.power_state` saves the
  original graphics mode and the switchable-graphics capability (it is
  application-specific, so it lives with the application package, not the
  generic harness)

```python
from handlers import system76_power
from handlers.system76_power import power_state
from handlers.system76_power import System76Power

# Save original state
h = System76Power()
power_state.save_original_graphics_mode_from(h)

# Restore later — True means a switch was ISSUED; the mode only changes on
# reboot, so the caller must reboot (conftest and pytest.sh both do).
power_state.restore_original_graphics_mode(h)
```

### Reboot confirmation and durable writes

`harness.reboot.system.reboot()` never claims success it cannot prove. Before
rebooting it records the kernel boot ID (`/proc/sys/kernel/random/boot_id`)
durably in three places: the run's persistent `reboot-marker`, the ephemeral
`/tmp/gui-testing-reboot-marker`, and `~/.local/share/gui-testing/boot-id`
(which lets no-run-dir calls like the end-of-session reboot confirm too).
After each attempted method it re-reads the boot ID; if no method ever changed
it — SysRq included — `reboot()` returns `False`.

`wait_for_boot()` likewise requires confirmation before returning `True`:
the current boot ID must differ from the recorded one, or the legacy marker
signature must hold (persistent marker present, `/tmp` marker gone). A system
that is up **on the same boot** gets a loud error and `False`, and every
reboot-aware workflow (`workflows/system76_power/{cli,gui}.py`) fails the
transition with a persisted `"reboot did not happen"` entry instead of
verifying against a machine that never rebooted.

All documents that must survive an abrupt `reboot(2)` issued moments later are
written through `harness.artifacts.manifest.durable_write_text()` (temp file →
`fsync` → atomic rename → directory `fsync`): manifests, phase-machine state
(`save_state`), the completion ledger and attempt counter (`resume.py`), the
reboot markers and boot-id file, `power_state` documents, and the recovery run
marker.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `GUI_TESTING_RESUME_RUN` | Path to run directory to resume |
| `GUI_TESTING_RESUMED` | Set to "1" for resumed runs |
| `GUI_TESTING_SETUP_DONE` | Set by pytest.sh after privileged setup |
| `GUI_TESTING_KEEP_REBOOT_SETUP` | Set to "1" to skip session cleanup (debugging) |
| `GUI_TESTING_RECOVER_MAX_AGE_MIN` | Marker freshness window for boot recovery (default 720) |
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
- State written before a reboot is durable (`durable_write_text`); if the
  phase machine still rolled back to "start", check that the write happened
  *before* the reboot command (look for `[persist_state] saved ...` in the log)

### "reboot did not happen" failures
- The harness now refuses to verify post-reboot state unless the kernel boot
  ID actually changed. If a transition test fails with
  `error: "reboot did not happen"`, the machine genuinely never left the
  previous boot — check the reboot-chain output printed just before it
  (rc for each method) and whether the sudoers grant for the privileged
  helper is still installed.

### Cleanup issues
- Normally there is nothing to do: the boot-time recovery unit repairs any
  leaked autologin/sudoers/resume-unit state at the next boot once the run
  marker is older than 12 hours.
- To repair immediately: `sudo python3 -m harness.reboot recover`
  (or `sudo -n /usr/local/libexec/gui-testing-privileged recover` while the
  grant is still live). `cleanup-all` also nukes persistent reboot markers.
- Last resort by hand: `sudo rm -f /etc/sudoers.d/gui-testing` and
  `rm -f ~/.config/systemd/user/gui-testing-resume.service`.
- If the recovery unit keeps firing on a run you want to keep set up, create
  `/var/lib/gui-testing/keep-setup`.
