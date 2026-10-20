#!/bin/bash

INPUT_TOOL="ydotool"
if [ "$XDG_SESSION_TYPE" == "x11" ]; then
    INPUT_TOOL="xdotool"
fi

if [ ! -d .venv ]; then
    # 1. Define all required packages
    REQUIRED_PKGS=(python3-pip python3-venv jq libinput-tools "$INPUT_TOOL")
    MISSING_PKGS=()

    # 2. Check each package individually and collect missing ones
    for pkg in "${REQUIRED_PKGS[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            MISSING_PKGS+=("$pkg")
        fi
    done

    # 3. If any packages are missing, update apt once and install them all at once
    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo "Installing missing dependencies: ${MISSING_PKGS[*]}"
        sudo apt update && sudo apt install -y "${MISSING_PKGS[@]}"
    fi

    # 4. Initialize and set up virtual environment safely
    python3 -m venv .venv
    
    # Use standard POSIX source
    . .venv/bin/activate
    
    # Use python3 -m pip to avoid wrapper/environment path bugs
    python3 -m pip install -U pip
    python3 -m pip install -r requirements.txt
fi

CONFIG_JSON_FILE="config.json"
CONFIG_JSON="{}"

# Load existing JSON if the file exists and is valid
if [[ -f "$CONFIG_JSON_FILE" ]]; then
    echo "Found existing '$CONFIG_JSON_FILE'. Checking nested values..."
    CONFIG_JSON=$(jq '.' "$CONFIG_JSON_FILE" 2>/dev/null || echo "{}")
fi

# Helper function to check if a specific key is populated
is_populated() {
    local path="$1"
    local value
    value=$(echo "$CONFIG_JSON" | jq -r "$path // empty")
    [[ -n "$value" ]]
}

echo "=== Ollama Configuration Check ==="

# 1. Check / Prompt for REMOTE_OLLAMA_IP
if is_populated ".ollama.REMOTE_OLLAMA_IP"; then
    ollama_ip=$(echo "$CONFIG_JSON" | jq -r '.ollama.REMOTE_OLLAMA_IP')
    echo "-> Ollama IP already populated: $ollama_ip"
else
    read -p "Enter Remote Ollama IP: " ollama_ip
fi

# 2. Check / Prompt for REMOTE_OLLAMA_PORT
if is_populated ".ollama.REMOTE_OLLAMA_PORT"; then
    ollama_port=$(echo "$CONFIG_JSON" | jq -r '.ollama.REMOTE_OLLAMA_PORT')
    echo "-> Ollama Port already populated: $ollama_port"
else
    read -p "Enter Remote Ollama Port [default: 11434]: " ollama_port
    ollama_port="${ollama_port:-11434}" # Fallback to 11434 if left blank
fi

# 3. Check / Prompt for model
if is_populated ".ollama.model"; then
    ollama_model=$(echo "$CONFIG_JSON" | jq -r '.ollama.model')
    echo "-> Ollama Model already populated: $ollama_model"
else
    read -p "Enter Ollama Model Name: " ollama_model
fi

# 4. Merge Ollama inputs into the JSON structure
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

# 5. Check if the input_tool is already recorded in the JSON
existing_tool=$(echo "$CONFIG_JSON" | jq -r '.input_tool // empty')

if [[ "$existing_tool" != "$INPUT_TOOL" ]]; then
    echo "-> Saving active input tool ($INPUT_TOOL) to configuration..."
    CONFIG_JSON=$(jq -n \
      --argjson existing "$CONFIG_JSON" \
      --arg tool "$INPUT_TOOL" \
      '$existing * {input_tool: $tool}')
fi

# 6. Handle ydotool hardware metrics if active
if [ "$INPUT_TOOL" == "ydotool" ]; then
    echo "ydotool active. Querying acceleration profile..."

    # POSIX/Mawk compatible block processor
    active_profile=$(sudo libinput list-devices | awk -v RS="" '
        /Device:[^\n]*ydotoold/ {
            idx = index($0, "Accel profiles:")
            if (idx > 0) {
                sub_str = substr($0, idx + 15)
                nl_idx = index(sub_str, "\n")
                if (nl_idx > 0) sub_str = substr(sub_str, 1, nl_idx - 1)
                
                num_fields = split(sub_str, profiles, /[ \t]+/)
                for (i = 1; i <= num_fields; i++) {
                    if (profiles[i] ~ /^\*/) {
                        sub(/^\*/, "", profiles[i])
                        print profiles[i]
                    }
                }
            }
        }
    ')

    if [[ -z "$active_profile" ]]; then
        active_profile="unknown"
    fi

    # Check if the active profile is already populated in your config.json
    existing_profile=$(echo "$CONFIG_JSON" | jq -r '.ydotool.active_profile // empty')

    if [[ -n "$existing_profile" ]]; then
        echo "-> Active profile already populated in JSON: $existing_profile (Skipping)"
    else
        echo "-> Updating JSON with active profile configuration..."
        CONFIG_JSON=$(jq -n \
          --argjson existing "$CONFIG_JSON" \
          --arg profile "$active_profile" \
          '
          {
            ydotool: {
              active_profile: $profile
            }
          } as $new
          | $existing * $new
          ')
    fi
fi

# 7. Write out to the file with a pretty-print formatting pass
echo "$CONFIG_JSON" | jq '.' > "$CONFIG_JSON_FILE"
echo "-----------------------------------"
echo "Current state of $CONFIG_JSON_FILE:"
cat "$CONFIG_JSON_FILE"
