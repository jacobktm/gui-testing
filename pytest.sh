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
        sbssas "screenshot" true "com.system76.CosmicScreenshot" "screenshot" 1 "granted" \
        >/dev/null 2>&1 || true
fi

# --- Determine if reboot test setup is needed ---
NEEDS_REBOOT_SETUP=false
if [[ "${RUN_DESTRUCTIVE_TESTS:-}" == "1" ]]; then
    # Reboot setup is needed for brightness reboot test and any graphics
    # transition tests. Enable whenever destructive tests run.
    NEEDS_REBOOT_SETUP=true
fi

# --- Privileged setup (passwordless sudo for harness.reboot commands) ---
SUDOERS_FILE="/etc/sudoers.d/gui-testing"
CREATED_SUDOERS=false

if $NEEDS_REBOOT_SETUP; then
    echo ""
    echo "Switchable graphics detected — setting up passwordless sudo for reboot tests."
    echo "You will be prompted for your sudo password once."
    echo ""

    # Create sudoers rule (prompts for password)
    SUDOERS_CONTENT="$USER ALL=(ALL) NOPASSWD: /usr/bin/python3 -m harness.reboot *, /usr/bin/systemctl restart com.system76.PowerDaemon.service, /usr/bin/systemctl reboot, /usr/sbin/reboot, /sbin/reboot, /usr/sbin/reboot -f, /sbin/reboot -f, /usr/bin/tee /proc/sysrq-trigger, /usr/bin/mkdir -p /var/lib/gui-testing, /usr/bin/tee /var/lib/gui-testing/*"
    echo "$SUDOERS_CONTENT" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 0440 "$SUDOERS_FILE"
    CREATED_SUDOERS=true
    export GUI_TESTING_SETUP_DONE=1

    # Create state directory for autologin config.
    sudo mkdir -p /var/lib/gui-testing
    sudo chmod 755 /var/lib/gui-testing

    # Verify it works
    if ! sudo -n python3 -m harness.reboot status > /dev/null 2>&1; then
        echo "Warning: passwordless sudo verification failed. Reboot tests may not work." >&2
    fi

    # Enable autologin (now passwordless)
    sudo -n python3 -m harness.reboot enable

    # Cleanup function: restore autologin + remove sudoers rule
    cleanup() {
        echo ""
        echo "Cleaning up reboot test setup..."
        sudo -n python3 -m harness.reboot restore 2>/dev/null || true
        sudo -n python3 -m harness.reboot cleanup 2>/dev/null || true
        # Restore original graphics mode if tests changed it.
        python3 -c "from handlers.system76_power import System76Power; h=System76Power(); h.restore_original_graphics_mode() and h.reboot()" 2>/dev/null || true
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

if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
    echo "Running all tests (verbose)..."
    exec pytest -vv -s
else
    echo "Running: pytest -vv ${PYTEST_ARGS[*]}"
    exec pytest -vv -s "${PYTEST_ARGS[@]}"
fi
