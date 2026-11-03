# Configuration

## Config File

Create `config.json` from the example:

```bash
cp config.example.json config.json
```

### Options

```json
{
  "ollama": {
    "REMOTE_OLLAMA_IP": "192.168.1.100",
    "REMOTE_OLLAMA_PORT": "11434",
    "model": "qwen3-vl:8b"
  },
  "screenshot_tool": "cosmic-screenshot"
}
```

| Key | Description | Default |
|-----|-------------|---------|
| `ollama.REMOTE_OLLAMA_IP` | Ollama server IP address | `127.0.0.1` |
| `ollama.REMOTE_OLLAMA_PORT` | Ollama server port | `11434` |
| `ollama.model` | Multimodal model name | `qwen3-vl:8b` |
| `screenshot_tool` | Screenshot backend | Auto-detected |

### Loading

Configuration is loaded by `harness.config.config`. It looks for `config.json` in the repo root.

## Environment Variables

### Test Execution

| Variable | Description | Default |
|----------|-------------|---------|
| `RUN_DESTRUCTIVE_TESTS` | Run destructive/reboot tests | `1` |
| `GUI_TESTING_ARTIFACTS` | Override artifacts directory | `./artifacts` |
| `GUI_TESTING_RESUME_RUN` | Resume from specific run directory | - |
| `GUI_TESTING_RESUMED` | Indicates resumed run | - |
| `GUI_TESTING_SETUP_DONE` | Privileged setup completed | - |
| `GUI_TESTING_KEEP_REBOOT_SETUP` | Don't clean up reboot setup | - |

### Ollama (overrides config)

Can be set via environment or passed to components. The config file takes precedence in most cases.

### Display/Desktop

| Variable | Description |
|----------|-------------|
| `XDG_SESSION_TYPE` | `wayland` or `x11` |
| `XDG_CURRENT_DESKTOP` | Desktop environment name |
| `WAYLAND_DISPLAY` | Wayland display |
| `DISPLAY` | X11 display |

### OS Detection

| Variable | Description |
|----------|-------------|
| `TEST_OS_ID` | Override OS ID for tests |
| `OS_ID` | OS ID used by workflows |

## Screenshot Backends

Auto-detected by `setup.sh` based on desktop environment:

| Desktop | Backend | Notes |
|---------|---------|-------|
| COSMIC | `cosmic-screenshot` | Native COSMIC screenshot tool |
| GNOME | `gnome-dotool` | Uses Shift+Print via dotool |
| Pop!_OS 22.04 (jammy) | `gnome-dotool` | Treated as GNOME |
| Default | `cosmic-screenshot` | Fallback |

## Dotool

`dotool` is built and installed by `setup.sh`. It requires:
- uinput kernel module
- Appropriate permissions (usually added to input/uinput groups)

## Artifacts

### Location

Default: `./artifacts/` or `$GUI_TESTING_ARTIFACTS`

Each run creates: `artifacts/YYYY-MM-DD_HH-MM-SS/`

### Retention

Configured in `conftest.py`:
```python
plan = RetentionPlan((KeepLast(10), KeepFailures()))
```

- Keep last 10 runs
- Always keep runs with failures

## Pytest Configuration

See `pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
markers =
    system76_power: tests for the system76-power program
    cli: CLI tests
    gui: GUI tests
    gnome: GNOME/Shell tests
    cosmic: COSMIC desktop tests
    destructive: Destructive tests
    reboot: Tests requiring reboot
    graphics_individual: Individual graphics transition tests (run explicitly)
```

## Virtual Environment

Created at `./.venv/` by `setup.sh`. Use `pytest.sh` to run tests with venv activated.

## Dependencies

### Runtime
- `ollama>=0.6` - Ollama Python client
- `pillow>=11` - Image processing

### Development
- `pytest>=8` - Testing framework
- `hypothesis>=6` - Property-based testing

### System
- `dotool` - Input injection (built from source)
- Various X11/Wayland tools
- `python3.11+` with venv support
