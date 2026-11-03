# GUI Testing Framework

A general-purpose, vision-driven GUI/CLI test automation framework for Linux desktops. Originally built to test `system76-power`, the framework is designed to be extensible to other applications.

## Features

- **Vision-based UI automation** - Set-of-Mark (SoM) detection using OpenCV + multimodal LLM (Ollama) to identify and click UI elements without brittle selectors.
- **Cross-desktop support** - Works on GNOME (Pop!_OS 22.04, Ubuntu) and COSMIC (Pop!_OS 24.04) with desktop-specific screenshot/input backends.
- **Input injection** - Uses `dotool` for mouse/keyboard input on both X11 and Wayland.
- **Artifact collection** - Per-run artifacts with manifests, retention policies, and automatic reporting.
- **Reboot/resume** - Handles tests that require rebooting (e.g., graphics mode changes) with autologin/resume state persistence.
- **CLI + GUI testing** - Test both command-line interfaces and GUI interactions through the same framework.
- **App-agnostic core** - Reusable harness primitives; app-specific orchestration lives in `workflows/`.

## Architecture

```
gui-testing/
├── harness/           # Framework core (generic, reusable)
│   ├── screenshots/   # Screenshot capture (cosmic-screenshot, gnome-dotool)
│   ├── gui/           # GuiDriver, Set-of-Mark, coordinates
│   ├── ollama_client/ # LLM integration
│   ├── dotool/        # Input injection
│   ├── detection/     # Response parsing
│   ├── artifacts/     # Run artifacts, manifests, retention
│   ├── reboot/        # Reboot/resume/autologin management
│   ├── report/        # Report generation
│   ├── workflows/     # Generic workflow base classes + UIWorkflow
│   └── power_state.py # Power/graphics state persistence
├── handlers/          # App control interfaces
│   └── system76_power/# system76-power CLI wrapper
├── workflows/         # App-specific test orchestration (moved out of harness)
│   └── system76_power/# CLI/GUI/profile/graphics transition workflows
├── tests/             # Pytest tests organized by app
│   └── system76-power/
└── docs/              # Detailed documentation
```

### Separation of Concerns

- **`harness/`** - Generic primitives that any app can use (screenshots, vision detection, input, artifacts, reboot handling). Includes `Workflow` base class and `UIWorkflow` for common UI patterns.
- **`handlers/`** - Low-level control of applications (e.g., wrapping `system76-power` CLI).
- **`workflows/`** - High-level test orchestration specific to an application (how to test profiles, graphics modes, etc.).
- **`tests/`** - Pytest test cases organized by application.

## Requirements

- Linux (Wayland or X11)
- Python 3.11+
- `dotool` (built/installed by setup)
- Ollama server with a multimodal model (e.g., `qwen3-vl:8b`)
- Desktop environment: GNOME or COSMIC
- For reboot tests: sudo access (setup.sh configures passwordless sudo temporarily)

## Setup

### 1. Initial Setup

```bash
./setup.sh
```

This will:
1. Detect OS/desktop environment and choose appropriate screenshot backend
2. Install system dependencies (including building `dotool`)
3. Create a Python virtual environment
4. Install Python dependencies
5. Prompt for configuration (Ollama host/port/model)

### 2. Configure

Copy and edit the config file:
```bash
cp config.example.json config.json
```

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

### 3. Run Tests

```bash
# Run all tests
./pytest.sh

# Run tests for a specific app
./pytest.sh system76-power

# Run a specific test file
./pytest.sh system76-power/test_cli_full.py

# Run with pytest filters
./pytest.sh -k "brightness"

# Clean old artifacts and run
./pytest.sh --clean

# Skip destructive/reboot tests
RUN_DESTRUCTIVE_TESTS=0 ./pytest.sh
```

## How It Works

### Vision-Based UI Detection (Set-of-Mark)

1. **Capture screenshot** using desktop-appropriate tool
2. **Crop to active display** 
3. **Detect UI elements** with OpenCV (buttons, dropdowns, etc.)
4. **Annotate with numeric IDs** (Set-of-Mark)
5. **Ask LLM** which ID corresponds to the target element
6. **Parse response** and convert to normalized coordinates
7. **Click via dotool**

This approach is resilient to UI changes and works across different desktop environments.

### Workflow Pattern

Workflows inherit from `harness.workflows.Workflow` and return `WorkflowResult` objects:

```python
from workflows.system76_power import System76PowerCLIWorkflow

wf = System76PowerCLIWorkflow(artifacts=artifacts)
result = wf.query_profile()
print(result.success, result.summary)
```

Generic UI workflows are available in `harness.workflows.UIWorkflow` for building app-agnostic UI interactions.

### Artifacts

Each test run creates a timestamped directory under `artifacts/` containing:
- Screenshots
- LLM prompts/responses
- Test logs
- Manifest with test status
- Summary reports

## Adding a New Application

See [docs/adding-applications.md](docs/adding-applications.md) for detailed instructions on extending the framework for a new app.

## Documentation

- [Architecture Overview](docs/architecture.md) - Deep dive into framework design
- [Adding Applications](docs/adding-applications.md) - Guide to extending for new apps
- [Workflows](docs/workflows.md) - Workflow patterns and API
- [GUI Automation](docs/gui-automation.md) - Vision detection, Set-of-Mark, coordinates
- [Reboot Handling](docs/reboot-handling.md) - Reboot/resume mechanism
- [Configuration](docs/configuration.md) - Config options and environment variables
- [Testing Guide](docs/testing.md) - Writing and running tests

## License

See repository for license information.
