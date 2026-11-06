#!/usr/bin/env bash
# pytest.sh — Activate the venv and run pytest.
#
# Usage:
#   ./pytest.sh                                    # run all tests (verbose)
#   ./pytest.sh system76-power                     # resolves to tests/system76-power/
#   ./pytest.sh system76-power/test_cli_full.py    # resolves to tests/system76-power/test_cli_full.py
#   ./pytest.sh tests/harness                      # run a directory
#   ./pytest.sh -k "reboot"                        # pass any pytest args
#   ./pytest.sh --clean                            # remove old artifact runs, then run
#   ./pytest.sh --clean-only                        # remove old artifact runs and exit
#
# Environment variables:
#   RUN_DESTRUCTIVE_TESTS=1   enable destructive/reboot tests
#   GUI_TESTING_ARTIFACTS     override artifacts root directory

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Run destructive/reboot tests by default (this harness is for system testing)
export RUN_DESTRUCTIVE_TESTS="${RUN_DESTRUCTIVE_TESTS:-1}"

VENV_DIR="$SCRIPT_DIR/.venv"
if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
    echo "Error: virtual environment not found at $VENV_DIR" >&2
    echo "Run setup.sh first." >&2
    exit 1
fi

# --- Parse flags ---
CLEAN=false
CLEAN_ONLY=false
PYTEST_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --clean)
            CLEAN=true
            ;;
        --clean-only)
            CLEAN=true
            CLEAN_ONLY=true
            ;;
        *)
            # Resolve shorthand: if arg doesn't exist as a path but
            # tests/<arg> does, use that.
            if [[ ! -e "$arg" && -e "tests/$arg" ]]; then
                PYTEST_ARGS+=("tests/$arg")
            else
                PYTEST_ARGS+=("$arg")
            fi
            ;;
    esac
done

# --- Cleanup old artifact runs ---
if $CLEAN; then
    ARTIFACTS_ROOT="${GUI_TESTING_ARTIFACTS:-$SCRIPT_DIR/artifacts}"
    if [[ -d "$ARTIFACTS_ROOT" ]]; then
        mapfile -t RUNS < <(ls -1dt "$ARTIFACTS_ROOT"/20* 2>/dev/null || true)
        if [[ ${#RUNS[@]} -gt 5 ]]; then
            echo "Cleaning old artifact runs (keeping 5 most recent)..."
            for run in "${RUNS[@]:5}"; do
                rm -rf "$run"
                echo "  removed $(basename "$run")"
            done
        else
            echo "No old artifact runs to clean (found ${#RUNS[@]})."
        fi
    fi
fi

if $CLEAN_ONLY; then
    echo "Cleanup complete."
    exit 0
fi

# --- Pre-grant screenshot permission on COSMIC (avoids dialog during tests) ---
if command -v cosmic-screenshot >/dev/null 2>&1; then
    busctl --user call org.freedesktop.impl.portal.PermissionStore \
        /org/freedesktop/impl/portal/PermissionStore \
        org.freedesktop.impl.portal.PermissionStore SetPermission \
        sbssas "screenshot" false "com.system76.CosmicScreenshot" "screenshot" 1 "granted" \
        >/dev/null 2>&1 || true

    # Trigger a test screenshot to surface the permission dialog early.
    # The user can dismiss it during setup so tests don't block on it.
    echo ""
    echo "Taking a test screenshot to verify permission (dismiss any dialog that appears)..."
    TEST_SHOT="/tmp/opencode/setup_test_shot.png"
    rm -f "$TEST_SHOT"
    timeout 10 cosmic-screenshot --interactive=false >/dev/null 2>&1 || true
    sleep 2
    if ls ~/Pictures/Screenshot_*.png >/dev/null 2>&1; then
        LATEST=$(ls -t ~/Pictures/Screenshot_*.png 2>/dev/null | head -1)
        if [ -n "$LATEST" ]; then
            mv "$LATEST" "$TEST_SHOT" 2>/dev/null || true
            echo "Screenshot OK: $TEST_SHOT"
        fi
    else
        echo "Warning: test screenshot may have failed. Permission dialog may appear during tests."
    fi
    echo ""
fi

# --- Determine if reboot test setup is needed ---
NEEDS_REBOOT_SETUP=false
if [[ "${RUN_DESTRUCTIVE_TESTS:-}" == "1" ]]; then
    # Reboot setup is needed for brightness reboot test and any graphics
    # transition tests. Enable whenever destructive tests run.
    NEEDS_REBOOT_SETUP=true
fi

# --- Privileged setup: one narrow sudoers grant plus a root-owned helper ---
# The old rule granted "python3 -m harness.reboot <subcmd>" plus tee/cat/rm on
# assorted paths.  That is a root escalation: sudo keeps the caller's working
# directory and python puts it on sys.path, so any local process could run
# arbitrary code as root from a hostile CWD.  The rule below grants a single
# fixed, root-owned script instead, and that script decides what may happen.
SUDOERS_FILE="/etc/sudoers.d/gui-testing"
PRIV_BIN="/usr/local/libexec/gui-testing-privileged"
PRIV_SNAPSHOT="/usr/local/libexec/gui-testing"
CREATED_SUDOERS=false
export GUI_TESTING_PRIVILEGED_HELPER="$PRIV_BIN"
export GUI_TESTING_PRIVILEGED_SNAPSHOT="$PRIV_SNAPSHOT"

install_privileged_helper() {
    # Copy the code that will run as root into a root-owned location outside the
    # repository, then install the wrapper that executes it.  Refreshed every
    # run, so it always matches the checkout that asked for it.
    sudo install -d -m 0755 -o root -g root "$PRIV_SNAPSHOT" || return 1
    sudo rm -rf "$PRIV_SNAPSHOT/harness"
    sudo cp -a "$SCRIPT_DIR/harness" "$PRIV_SNAPSHOT/harness" || return 1
    sudo find "$PRIV_SNAPSHOT" -name '__pycache__' -type d -exec rm -rf '{}' + 2>/dev/null
    sudo chown -R root:root "$PRIV_SNAPSHOT" || return 1
    sudo chmod -R u=rwX,go=rX "$PRIV_SNAPSHOT" || return 1

    local wrapper
    wrapper="$(mktemp)"
    cat > "$wrapper" <<WRAPPER
#!/bin/sh
# Installed by pytest.sh - do not edit, regenerated on every run.
# Runs the reboot/autologin helper from a root-owned snapshot so the
# passwordless sudo grant can never point at user-writable code.
set -eu
cd "$PRIV_SNAPSHOT" || exit 1
if [ -x /usr/bin/python3 ]; then
    PY=/usr/bin/python3
else
    PY=python3
fi
exec "\$PY" -B -s -m harness.reboot "\$@"
WRAPPER
    sudo install -m 0755 -o root -g root "$wrapper" "$PRIV_BIN" || { rm -f "$wrapper"; return 1; }
    rm -f "$wrapper"
}

if $NEEDS_REBOOT_SETUP; then
    echo ""
    echo "Setting up passwordless sudo for reboot/autologin (helper: $PRIV_BIN)."
    echo "You will be prompted for your sudo password once."
    echo ""

    if ! install_privileged_helper; then
        echo "Warning: could not install the privileged helper." >&2
        echo "Reboot tests will not be able to reboot unattended." >&2
    else
        # Build the rule, validate it, and only then install it.
        sudoers_tmp="$(mktemp)"
        cat > "$sudoers_tmp" <<SUDOERS
# Installed by pytest.sh for the GUI test harness; regenerated on every run.
# Three grants, all fixed absolute paths with no wildcards:
#   * the root-owned helper (reboot, autologin, state and unit cleanup)
#   * an orderly reboot, kept so a reboot is still possible if the helper
#     snapshot is missing (reboot only - it executes no user code)
#   * restarting the power daemon, which the brightness/graphics tests do
Defaults env_reset
$USER ALL=(root) NOPASSWD: $PRIV_BIN
$USER ALL=(root) NOPASSWD: /usr/bin/systemctl reboot
$USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart com.system76.PowerDaemon.service
SUDOERS
        if sudo visudo -cf "$sudoers_tmp" >/dev/null 2>&1; then
            sudo install -m 0440 -o root -g root "$sudoers_tmp" "$SUDOERS_FILE"
            CREATED_SUDOERS=true
            export GUI_TESTING_SETUP_DONE=1
        else
            echo "Warning: the sudoers rule failed visudo validation; not installed." >&2
            echo "Reboot tests will not be able to reboot unattended." >&2
            if sudo test -e "$SUDOERS_FILE"; then
                echo "Stale rule still present: sudo rm -f $SUDOERS_FILE" >&2
            fi
        fi
        rm -f "$sudoers_tmp"
    fi

    if $CREATED_SUDOERS; then
        # State directory for the display-manager configuration snapshot.
        sudo mkdir -p /var/lib/gui-testing
        sudo chmod 755 /var/lib/gui-testing

        # Verify the grant actually works before relying on it.
        if ! sudo -n "$PRIV_BIN" status > /dev/null 2>&1; then
            echo "Warning: passwordless sudo verification failed. Reboot tests may not work." >&2
        fi

        # Enable autologin (now passwordless).
        sudo -n "$PRIV_BIN" enable

        # Install the boot-time recovery unit.  On every later boot it checks
        # for a fresh "run in progress" marker; when there is none it revokes
        # the sudoers rule, restores the display-manager config, deletes
        # resume units, and disables itself.  This is the guarantee that a
        # crashed or interrupted run can never leave the machine needing a
        # reinstall.  While hand-debugging a run you are about to resume,
        # "sudo touch /var/lib/gui-testing/keep-setup" makes recovery leave
        # everything alone.
        recover_script="$(mktemp)"
        recover_unit="$(mktemp)"
        if python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from harness.reboot.recovery import build_recover_script, build_recover_unit; open(sys.argv[2], "w").write(build_recover_script()); open(sys.argv[3], "w").write(build_recover_unit())' "$SCRIPT_DIR" "$recover_script" "$recover_unit"; then
            sudo install -m 0755 -o root -g root "$recover_script" /usr/local/libexec/gui-testing-recover \
                || echo "Warning: could not install the recovery script." >&2
            sudo install -m 0644 -o root -g root "$recover_unit" /etc/systemd/system/gui-testing-recover.service \
                || echo "Warning: could not install the recovery unit." >&2
            sudo systemctl daemon-reload
            sudo systemctl enable gui-testing-recover.service \
                || echo "Warning: could not enable gui-testing-recover.service." >&2
        else
            echo "Warning: could not generate the recovery script; boot-time recovery unavailable." >&2
        fi
        rm -f "$recover_script" "$recover_unit"
    fi

    # Cleanup function: restore autologin + remove the sudoers rule.
    cleanup() {
        echo ""
        echo "Cleaning up reboot test setup..."
        sudo -n "$PRIV_BIN" restore 2>/dev/null || true
        sudo -n "$PRIV_BIN" cleanup 2>/dev/null || true
        # Restore idle/lock settings
        python3 -c "from harness.reboot import restore_idle; restore_idle()" 2>/dev/null || true
        # Restore original graphics mode if tests changed it.  A switch is
        # only a config write until rebooted, so reboot when one was issued.
        python3 -c "
from handlers.system76_power import System76Power
from handlers.system76_power.power_state import restore_original_graphics_mode
h = System76Power()
if restore_original_graphics_mode(h):
    from harness.reboot.system import reboot, wait_for_boot
    reboot(None)
    wait_for_boot(None)
" 2>/dev/null || true
        # Restore brightness to max (tests may leave it at min).
        python3 -c "from harness.brightness import BrightnessHandler; BrightnessHandler().brightness_up_to_max()" 2>/dev/null || true
        # Clean up persistent reboot markers.
        rm -f "$SCRIPT_DIR"/artifacts/*/reboot-marker 2>/dev/null || true
    }
    trap cleanup EXIT
fi

# --- Activate venv and run pytest ---
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# Disable idle blanking / screen locking / idle suspend for the duration of the
# run.  conftest.py repeats this for resumed runs (it is idempotent), and the
# generated resume script re-applies it before pytest starts.  disable_idle()
# returns a structured report: applied keys with their read-back values and
# explicit errors (e.g. an unreachable session bus), so "applied 0" can no
# longer hide a protection that never took effect.
python3 -c "
from harness.reboot import save_idle_state, disable_idle
s = save_idle_state()
r = disable_idle()
print('idle backend:', s.get('desktop'), '| applied:', len(r['applied']), '| readback_ok:', r['readback_ok'])
for e in r['errors']:
    print('idle ERROR:', e)
if not r['applied'] or r['readback_ok'] is False:
    print('WARNING: idle protection is NOT active — GUI tests may hit a locked screen')
"

# Do NOT exec: the EXIT trap (cleanup) must run on normal completion.  A hard
# reboot mid-run still kills this shell before any trap can fire; the boot-time
# recovery unit installed above covers that case.
if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
    echo "Running all tests (verbose)..."
    pytest -vv -s
    status=$?
else
    echo "Running: pytest -vv ${PYTEST_ARGS[*]}"
    pytest -vv -s "${PYTEST_ARGS[@]}"
    status=$?
fi
exit "$status"
