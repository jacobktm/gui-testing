#!/usr/bin/env bash
# pytest.sh — Activate the venv and run pytest.
#
# Usage:
#   ./pytest.sh                                    # run all tests
#   ./pytest.sh tests/harness                      # run a directory
#   ./pytest.sh tests/harness/test_reboot_session.py  # run a file
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
            PYTEST_ARGS+=("$arg")
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

# --- Determine if reboot test setup is needed ---
# Only when RUN_DESTRUCTIVE_TESTS=1 AND the system has switchable graphics.
NEEDS_REBOOT_SETUP=false
if [[ "${RUN_DESTRUCTIVE_TESTS:-}" == "1" ]]; then
    if system76-power graphics switchable 2>/dev/null | grep -qx "switchable"; then
        NEEDS_REBOOT_SETUP=true
    fi
fi

# --- Privileged setup (prompts for sudo password before any tests run) ---
if $NEEDS_REBOOT_SETUP; then
    echo ""
    echo "Switchable graphics detected — setting up autologin for reboot tests."
    echo "You may be prompted for your sudo password."
    echo ""
    sudo python3 -m harness.reboot enable
    export GUI_TESTING_SETUP_DONE=1

    # Restore autologin config when pytest exits (covers non-reboot completion).
    # Reboots will kill this process; the resumed run handles its own cleanup.
    cleanup() {
        echo ""
        echo "Restoring autologin configuration..."
        sudo python3 -m harness.reboot restore 2>/dev/null || true
    }
    trap cleanup EXIT
fi

# --- Activate venv and run pytest ---
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
    echo "Running all tests..."
    exec pytest
else
    echo "Running: pytest ${PYTEST_ARGS[*]}"
    exec pytest "${PYTEST_ARGS[@]}"
fi
