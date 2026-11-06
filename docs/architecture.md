# Architecture Overview

This document describes the internal architecture of the GUI Testing Framework.

## Design Principles

1. **Separation of concerns** - Framework core (harness) is generic; app-specific logic lives in handlers/workflows
2. **Vision-driven** - Prefer UI interaction via screenshots + LLM over brittle accessibility APIs
3. **Resilient** - Handle failures gracefully, retry on transient issues, persist state across reboots
4. **Extensible** - Easy to add new applications without modifying core framework

## Component Overview

### Harness (`harness/`) - Generic Framework

The harness provides reusable primitives for GUI/CLI automation.

| Module | Purpose |
|--------|---------|
| `screenshots/` | Capture screenshots using desktop-appropriate tools (cosmic-screenshot, gnome-dotool) |
| `gui/` | GuiDriver for input simulation, Set-of-Mark detection, coordinate transformation |
| `ollama_client/` | HTTP client for Ollama API, handles image encoding |
| `dotool/` | Low-level input injection via dotool (mouse/keyboard) |
| `detection/` | Parse LLM responses into structured data |
| `imageutils/` | Image processing utilities (cropping, etc.) |
| `artifacts/` | Run artifacts management, manifests, retention policies |
| `reboot/` | Reboot orchestration, autologin setup, state persistence across reboots |
| `report/` | Generate test reports |
| `workflows/base.py` | `Workflow` base class, `WorkflowResult` dataclass |
| `workflows/ui_workflow.py` | Generic UI interaction patterns |
| `config/` | Configuration loading |
| `brightness/` | Backlight brightness control |
| `display/` | Display detection and geometry |

### Handlers (`handlers/`) - App Control

Handlers wrap applications to provide a consistent interface.

| Module | Purpose |
|--------|---------|
| `system76_power/` | Wrapper around `system76-power` CLI for profiles, graphics modes, etc. |

Handlers are typically thin wrappers around CLI tools or system APIs.

### Workflows (`workflows/`) - App-Specific Orchestration

Workflows implement test logic for specific applications. Moved out of harness to maintain clear separation.

| Module | Purpose |
|--------|---------|
| `system76_power/base_workflow.py` | Base workflow with common system76-power operations |
| `system76_power/cli.py` | CLI-focused workflows (profile queries, transitions via CLI) |
| `system76_power/gui.py` | GUI-focused workflows (navigating settings UI) |
| `system76_power/transitions.py` | `ProfileTransitionWorkflow` - UI validation of power profiles (graphics transitions share `graphics_transitions.py`) |

### Tests (`tests/`) - Test Cases

Pytest tests organized by application directory. Tests use workflows and handlers to interact with the system.

## Data Flow

### GUI Test Flow

1. **Test starts** → `conftest.py` sets up artifacts, checks for reboot state
2. **Workflow created** → Instantiates appropriate workflow with artifacts
3. **UI navigation** → `UIWorkflow` or `GuiDriver` clicks to open settings
4. **Screenshot** → Capture and crop active display
5. **Set-of-Mark** → Detect elements, annotate, ask LLM to identify target
6. **Parse & act** → Get coordinates, click element
7. **Verify** → Take screenshot again, ask LLM to confirm state
8. **Record** → Save artifacts, update manifest

### Reboot Test Flow

1. **Before reboot** → `conftest.py` prepares autologin, installs resume unit, saves state
2. **Trigger reboot** → System reboots, autologin logs in
3. **After reboot** → Resume unit runs pytest with `--resume-run` pointing to previous artifacts
4. **Restore state** → Load completed tests, skip them, continue from where we left off
5. **Cleanup** → Restore original state, remove autologin/resume config

## Key Patterns

### Workflow Base Class

```python
class Workflow:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts
    
    def run(self, *args, **kwargs) -> WorkflowResult:
        raise NotImplementedError
    
    def persist_state(self, item_id, phase, state, step="state"): ...
    def load_persisted_state(self, item_id, phase="state"): ...
```

All workflows return `WorkflowResult(success, item_id, summary, data)`.

### GuiDriver

Central class for GUI automation:
- `go_to(coords)` - Move mouse
- `click_at(coords)` - Click
- `detect_coords_som(target_description)` - Find element via Set-of-Mark
- `detect_power_profile_som()` - Detect active profile
- `capture_and_detect()` - Full capture+detect flow

### Artifacts System

- `RunArtifacts` - Manages a single test run's artifacts
- `Manifest` - Tracks test status (passed/failed/unknown/skipped)
- `RetentionPlan` - Controls which runs to keep

## Extension Points

To add a new application:
1. Create `handlers/<app>/` for app control
2. Create `workflows/<app>/` for test orchestration
3. Create `tests/<app>/` for test cases
4. Update `conftest.py` `PROGRAMS` list if needed for markers
5. Add to `pyproject.toml` packages (workflows* already included)

See [adding-applications.md](docs/adding-applications.md) for details.
