#!/bin/bash
#
# Usage:
#   ./setup.sh            First-time setup: installs system deps, creates the
#                         venv, installs Python deps, and prompts for config.
#   ./setup.sh --update   Re-checks/reinstalls system deps and refreshes Python
#                         deps in the existing venv, then re-prompts for config
#                         fields using current values as defaults (blank = keep).

UPDATE_MODE=false
for arg in "$@"; do
    case "$arg" in
        -u|--update) UPDATE_MODE=true ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--update]" >&2
            exit 1
            ;;
    esac
done

INPUT_TOOL="ydotool"
if [[ "${XDG_SESSION_TYPE,,}" == "x11" ]]; then
    INPUT_TOOL="xdotool"
fi

# Determine the OS codename (e.g. jammy, noble) to pick release-specific tooling
if command -v lsb_release &> /dev/null; then
    OS_CODENAME=$(lsb_release -cs)
else
    OS_CODENAME=$(. /etc/os-release && echo "${VERSION_CODENAME:-unknown}")
fi

# jammy (22.04) uses scrot; noble (24.04) and newer ship cosmic-screenshot
if [[ "$OS_CODENAME" == "jammy" ]]; then
    SCREENSHOT_TOOL="scrot"
    SCREENSHOT_PKGS=(scrot)
else
    SCREENSHOT_TOOL="cosmic-screenshot"
    SCREENSHOT_PKGS=()
fi

echo "Detected OS codename: $OS_CODENAME -> screenshot tool: $SCREENSHOT_TOOL"

# ==============================================================================
# 1. VERIFY AND INSTALL MINIMUM PYTHON 3.11+
# ==============================================================================
TARGET_PYTHON=""

for version in 13 12 11; do
    if command -v "python3.${version}" &> /dev/null; then
        TARGET_PYTHON="python3.${version}"
        break
    fi
done

if [ -z "$TARGET_PYTHON" ] && command -v python3 &> /dev/null; then
    py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    major=$(echo "$py_version" | cut -d. -f1)
    minor=$(echo "$py_version" | cut -d. -f2)
    
    if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
        TARGET_PYTHON="python3"
    fi
fi

if [ -z "$TARGET_PYTHON" ]; then
    echo "Python 3.11 or greater is not installed. Installing Python 3.11..."
    if ! grep -q "^deb.*deadsnakes" /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; then
        echo "Adding deadsnakes PPA repository..."
        sudo apt-get update
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
    fi
    sudo apt update
    sudo apt install -y python3.11 python3.11-venv python3.11-dev
    TARGET_PYTHON="python3.11"
fi

echo "Using system execution host: $TARGET_PYTHON ($($TARGET_PYTHON --version))"

# ==============================================================================
# 2. CHECK AND INSTALL SYSTEM PACKAGES
# ==============================================================================
VENV_PACKAGE="${TARGET_PYTHON}-venv"
if [ "$TARGET_PYTHON" == "python3" ]; then
    VENV_PACKAGE="python3-venv"
fi

REQUIRED_PKGS=(python3-pip "$VENV_PACKAGE" jq libinput-tools "$INPUT_TOOL" "${SCREENSHOT_PKGS[@]}")
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
        MISSING_PKGS+=("$pkg")
    fi
done

# On first run (or in update mode) make sure all system packages are present
if [ ! -d .venv ] || [ "$UPDATE_MODE" == true ]; then
    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "Installing missing dependencies: ${MISSING_PKGS[*]}"
        sudo apt update && sudo apt install -y "${MISSING_PKGS[@]}"
    else
        echo "All system dependencies already installed."
    fi
fi

if [ ! -d .venv ]; then
    $TARGET_PYTHON -m venv .venv
fi

# Enter the venv and (re)install Python dependencies
. .venv/bin/activate
if [ "$UPDATE_MODE" == true ]; then
    echo "Update mode: refreshing pip and Python dependencies..."
    python3 -m pip install -U pip
    python3 -m pip install -U -r requirements.txt
elif [ ! -f .venv/.deps_installed ]; then
    python3 -m pip install -U pip
    python3 -m pip install -r requirements.txt
    touch .venv/.deps_installed
fi

# ==============================================================================
# 3. CONFIGURE FILE READS AND WRITES
# ==============================================================================
CONFIG_JSON_FILE="config.json"
CONFIG_JSON="{}"

if [[ -f "$CONFIG_JSON_FILE" ]]; then
    echo "Found existing '$CONFIG_JSON_FILE'. Checking nested values..."
    CONFIG_JSON=$(jq '.' "$CONFIG_JSON_FILE" 2>/dev/null || echo "{}")
fi

is_populated() {
    local path="$1"
    local value
    value=$(echo "$CONFIG_JSON" | jq -r "$path // empty")
    [[ -n "$value" ]]
}

echo "=== Ollama Configuration Check ==="

cur_ip=$(echo "$CONFIG_JSON" | jq -r '.ollama.REMOTE_OLLAMA_IP // empty')
cur_port=$(echo "$CONFIG_JSON" | jq -r '.ollama.REMOTE_OLLAMA_PORT // empty')
cur_model=$(echo "$CONFIG_JSON" | jq -r '.ollama.model // empty')

if [ "$UPDATE_MODE" == true ]; then
    read -p "Enter Remote Ollama IP [${cur_ip:-none}]: " ollama_ip
    ollama_ip="${ollama_ip:-$cur_ip}"

    read -p "Enter Remote Ollama Port [${cur_port:-11434}]: " ollama_port
    ollama_port="${ollama_port:-${cur_port:-11434}}"

    read -p "Enter Ollama Model Name [${cur_model:-none}]: " ollama_model
    ollama_model="${ollama_model:-$cur_model}"
else
    if is_populated ".ollama.REMOTE_OLLAMA_IP"; then
        ollama_ip="$cur_ip"
        echo "-> Ollama IP already populated: $ollama_ip"
    else
        read -p "Enter Remote Ollama IP: " ollama_ip
    fi

    if is_populated ".ollama.REMOTE_OLLAMA_PORT"; then
        ollama_port="$cur_port"
        echo "-> Ollama Port already populated: $ollama_port"
    else
        read -p "Enter Remote Ollama Port [default: 11434]: " ollama_port
        ollama_port="${ollama_port:-11434}"
    fi

    if is_populated ".ollama.model"; then
        ollama_model="$cur_model"
        echo "-> Ollama Model already populated: $ollama_model"
    else
        read -p "Enter Ollama Model Name: " ollama_model
    fi
fi

CONFIG_JSON=$(jq -n \
  --argjson existing "$CONFIG_JSON" \
  --arg ip "$ollama_ip" \
  --arg port "$ollama_port" \
  --arg model "$ollama_model" \
  '
  {
    ollama: {
      REMOTE_OLLAMA_IP: $ip,
      REMOTE_OLLAMA_PORT: $port,
      model: $model
    }
  } as $new_ollama
  | $existing * $new_ollama
  ')

echo "=== Hardware Input Configuration Check ==="

existing_tool=$(echo "$CONFIG_JSON" | jq -r '.input_tool // empty')

if [[ "$existing_tool" != "$INPUT_TOOL" ]]; then
    echo "-> Saving active input tool ($INPUT_TOOL) to configuration..."
    CONFIG_JSON=$(jq -n \
      --argjson existing "$CONFIG_JSON" \
      --arg tool "$INPUT_TOOL" \
      '$existing * {input_tool: $tool}')
fi

existing_screenshot_tool=$(echo "$CONFIG_JSON" | jq -r '.screenshot_tool // empty')

if [[ "$existing_screenshot_tool" != "$SCREENSHOT_TOOL" ]]; then
    echo "-> Saving screenshot tool ($SCREENSHOT_TOOL) to configuration..."
    CONFIG_JSON=$(jq -n \
      --argjson existing "$CONFIG_JSON" \
      --arg tool "$SCREENSHOT_TOOL" \
      '$existing * {screenshot_tool: $tool}')
fi

echo "$CONFIG_JSON" | jq '.' > "$CONFIG_JSON_FILE"
echo "-----------------------------------"
echo "Current state of $CONFIG_JSON_FILE:"
cat "$CONFIG_JSON_FILE"
