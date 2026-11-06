# Testing Guide

## Running Tests

### Basic Usage

```bash
# Run all tests
./pytest.sh

# Run tests for specific app
./pytest.sh system76-power

# Run specific test file
./pytest.sh system76-power/test_brightness.py

# Run specific test
./pytest.sh system76-power/test_brightness.py::TestBrightness::test_brightness_balanced_max

# Pass pytest options
./pytest.sh -v -k "cli"
./pytest.sh --tb=short
```

### Cleanup Options

```bash
# Clean old artifacts (keep 5 most recent) then run
./pytest.sh --clean

# Just clean artifacts
./pytest.sh --clean-only
```

### Environment Control

```bash
# Skip destructive/reboot tests
RUN_DESTRUCTIVE_TESTS=0 ./pytest.sh

# Use different artifacts directory
GUI_TESTING_ARTIFACTS=/tmp/artifacts ./pytest.sh

# Resume a previous run
./pytest.sh --resume-run artifacts/2024-01-01_12-00-00
```

## Test Organization

Tests are organized by application:
```
tests/
└── system76-power/
    ├── test_brightness.py
    ├── test_cli_full.py
    ├── test_gui_profile.py
    ├── test_gui_graphics.py
    ├── test_perf_profile.py
    └── test_power_daemon.py
```

## Test Markers

Use markers to categorize tests:

```python
import pytest

class TestExample:
    @pytest.mark.cli
    def test_cli_operation(self):
        ...
    
    @pytest.mark.gui
    def test_gui_operation(self):
        ...
    
    @pytest.mark.reboot
    def test_requires_reboot(self):
        ...
    
    @pytest.mark.destructive
    def test_changes_system_state(self):
        ...
    
    @pytest.mark.gnome
    def test_gnome_specific(self):
        ...
    
    @pytest.mark.cosmic
    def test_cosmic_specific(self):
        ...
```

Markers are automatically applied based on test location and can be used for filtering.

## Writing Tests

### Basic Test Structure

```python
import pytest
from workflows.myapp import MyAppCLIWorkflow


class TestMyApp:
    def test_something(self, artifacts):
        wf = MyAppCLIWorkflow(artifacts=artifacts)
        result = wf.do_something()
        assert result.success, result.summary
```

### Using Artifacts

The `artifacts` fixture provides `RunArtifacts` instance:

```python
def test_with_artifacts(self, artifacts):
    wf = MyAppWorkflow(artifacts=artifacts)
    
    # Workflow will save artifacts automatically
    result = wf.do_something(item_id="myapp.test.item")
    
    # Or save manually
    artifacts.save_text("myapp.test.item", "custom", "data\n", step="debug")
    artifacts.save_image("myapp.test.item", "screenshot", image_path)
```

### GUI Tests

```python
@pytest.mark.gui
class TestMyAppGUI:
    def test_change_via_gui(self, artifacts):
        from workflows.myapp import MyAppGUIWorkflow
        wf = MyAppGUIWorkflow(artifacts=artifacts)
        result = wf.change_via_gui("value")
        assert result.success
```

### Reboot Tests

```python
@pytest.mark.reboot
@pytest.mark.destructive
def test_persistent_setting(self, artifacts):
    # Setup before reboot
    ...
    # Trigger reboot
    ...
    # After reboot, test continues/resumes
    ...
```

### Skipping Tests

```python
import pytest

def test_requires_feature(self, artifacts):
    if not feature_available():
        pytest.skip("feature not available")
    ...
```

## Debugging

### View Artifacts

Artifacts are saved in `artifacts/<run_timestamp>/`:
- `manifest.json` - Test results
- `summary.txt` - Human-readable summary
- `report.json` - Detailed report
- Per-test directories with screenshots, logs, etc.

### Run with More Verbosity

```bash
./pytest.sh -vv --tb=long
```

### Debug Output

Workflows and harness code often print debug info to stdout/stderr which is captured by pytest.

### Interactive Debugging

```bash
# Run with pdb
./pytest.sh --pdb

# Drop into debugger on failure
./pytest.sh --pdb -x
```

## Best Practices

1. **Use workflows** - Don't call handlers directly in tests; use workflows for orchestration
2. **Provide item_id** - Helps with tracking and resume
3. **Check artifacts** - Look at saved screenshots/prompts when debugging
4. **Use appropriate markers** - Helps filter tests
5. **Handle environment differences** - Skip if not applicable to current OS/desktop
6. **Keep tests focused** - One logical test per test function
7. **Use fixtures** - The `artifacts` fixture is automatically provided
8. **Be patient with GUI tests** - Vision-based tests can be slower and less deterministic
9. **Add retries where needed** - Workflows often have built-in retries
10. **Clean up** - Framework handles most cleanup, but be mindful of system state

## Continuous Integration

For CI/headless environments:
- Use `RUN_DESTRUCTIVE_TESTS=0` to skip reboot/GUI tests
- Ensure the configured LLM server (Ollama or Strata) is accessible
- May need virtual display (Xvfb) for GUI tests
- Some tests require physical hardware (backlight, GPU switching)

## Performance Tips

- GUI tests are slow (screenshot + LLM inference)
- Use CLI tests where possible
- Run specific tests during development
- LLM inference time depends on model and hardware
- Set-of-Mark element detection is relatively fast
