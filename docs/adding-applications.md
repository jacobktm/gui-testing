# Adding New Applications

This guide explains how to extend the framework to test a new application.

## Overview

The framework is designed for easy extension. You need three components:
1. **Handler** - Low-level interface to control the application
2. **Workflow(s)** - High-level orchestration of test operations
3. **Tests** - Pytest test cases

## Step 1: Create a Handler

Handlers live in `handlers/<app_name>/`. They should provide a clean API for controlling the app.

### Example Structure

```
handlers/
└── myapp/
    ├── __init__.py
    └── myapp.py
```

### Example Implementation

```python
# handlers/myapp/__init__.py
from .myapp import MyApp

__all__ = ["MyApp"]
```

```python
# handlers/myapp/myapp.py
from __future__ import annotations

import subprocess
from typing import Any


class MyApp:
    def __init__(self, artifacts=None, test_id=None, item_id=None, phase=None):
        self.artifacts = artifacts
        self.test_id = test_id
        self.item_id = item_id
        self.phase = phase
    
    def do_something(self, arg: str) -> bool:
        try:
            result = subprocess.run(["myapp", "do-something", arg], 
                                  capture_output=True, timeout=30)
            return result.returncode == 0
        except Exception:
            return False
    
    def get_state(self) -> str | None:
        try:
            result = subprocess.run(["myapp", "status"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None
```

## Step 2: Create Workflows

Workflows live in `workflows/<app_name>/`. They orchestrate operations using handlers and harness primitives.

### Example Structure

```
workflows/
└── myapp/
    ├── __init__.py
    ├── base_workflow.py
    ├── cli.py
    └── gui.py
```

### Base Workflow

```python
# workflows/myapp/base_workflow.py
from __future__ import annotations

from handlers.myapp import MyApp
from harness.workflows.base import Workflow, WorkflowResult


class MyAppWorkflow(Workflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
    
    def check_status(self, item_id: str = "myapp.status") -> WorkflowResult:
        handler = MyApp(artifacts=self.artifacts)
        state = handler.get_state()
        
        if self.artifacts is not None and item_id:
            try:
                self.artifacts.save_text(
                    item_id, "verify",
                    f"state={state}\n",
                    step="myapp_status"
                )
            except Exception:
                pass
        
        return WorkflowResult(
            success=state is not None,
            item_id=item_id,
            summary=f"state={state}",
            data={"state": state},
        )
```

### CLI Workflow

```python
# workflows/myapp/cli.py
from __future__ import annotations

from handlers.myapp import MyApp
from harness.workflows.base import Workflow, WorkflowResult
from .base_workflow import MyAppWorkflow


class MyAppCLIWorkflow(MyAppWorkflow):
    def set_config(self, value: str, item_id: str = None) -> WorkflowResult:
        if item_id is None:
            item_id = f"cli.myapp.set_{value}"
        handler = MyApp(artifacts=self.artifacts)
        ok = handler.do_something(value)
        return WorkflowResult(
            success=ok,
            item_id=item_id,
            summary=f"set to {value}" if ok else "failed",
        )
```

### GUI Workflow (if needed)

For GUI testing, use `UIWorkflow` from `harness.workflows` or `GuiDriver` directly.

```python
# workflows/myapp/gui.py
from __future__ import annotations

from harness.workflows.base import Workflow, WorkflowResult
from harness.workflows.ui_workflow import UIWorkflow
from .base_workflow import MyAppWorkflow


class MyAppGUIWorkflow(MyAppWorkflow):
    def __init__(self, artifacts=None):
        super().__init__(artifacts=artifacts)
        self.ui = UIWorkflow(artifacts=artifacts)
    
    def change_via_gui(self, value: str, os_id: str = None, item_id: str = None) -> WorkflowResult:
        # Use UIWorkflow.detect_from_ui() or GuiDriver directly
        # Define coordinates for your app's UI elements
        ...
```

### Workflows `__init__.py`

```python
# workflows/myapp/__init__.py
from .base_workflow import MyAppWorkflow
from .cli import MyAppCLIWorkflow
from .gui import MyAppGUIWorkflow

__all__ = [
    "MyAppWorkflow",
    "MyAppCLIWorkflow", 
    "MyAppGUIWorkflow",
]
```

### Top-level workflows `__init__.py`

Optionally update `workflows/__init__.py` if you want to document it, but not required.

## Step 3: Create Tests

Tests go in `tests/<app_name>/`.

### Example Test

```python
# tests/myapp/test_basic.py
import pytest

from workflows.myapp import MyAppCLIWorkflow


class TestMyApp:
    def test_status_check(self, artifacts):
        wf = MyAppCLIWorkflow(artifacts=artifacts)
        result = wf.check_status()
        assert result.success, result.summary
    
    @pytest.mark.gui
    def test_gui_interaction(self, artifacts):
        wf = MyAppCLIWorkflow(artifacts=artifacts)
        # ...
```

### Update conftest.py (optional)

If you want automatic marker assignment, add your app to `PROGRAMS` in `conftest.py`:

```python
PROGRAMS = ["system76-power", "myapp"]
```

This will automatically add a `myapp` marker to tests in `tests/myapp/`.

## Step 4: Add Pytest Markers (optional)

Add markers to `pytest.ini`:

```ini
[pytest]
markers =
    system76_power: tests for the system76-power program
    myapp: tests for myapp
    ...
```

## Step 5: Update Packaging

The `pyproject.toml` already includes `workflows*` and `handlers*`, so new apps should be picked up automatically.

## Tips for GUI Testing

### Using UIWorkflow

`harness.workflows.UIWorkflow` provides generic methods:
- `open_ui_elements(clicks)` - Click through a sequence
- `detect_from_ui(clicks, prompt, expected)` - Full chain (screenshot + LLM)

### Using GuiDriver Directly

For more control:
```python
from harness.gui import GuiDriver

driver = GuiDriver(artifacts=artifacts)
coords = driver.detect_coords_som("the settings button")
if coords:
    driver.click_at(coords)
```

### Coordinates

Use `harness.gui.coords` for coordinate definitions and scaling across different resolutions:
```python
from harness.gui import Coords
from harness.gui.coords import adjust_coords, get_display_resolution
```

### Prompts

Use templates from `harness.llm.prompts`:
```python
from harness.llm.prompts import SIMPLE_SELECTION, SETTINGS_SELECTION
prompt = SIMPLE_SELECTION.render(item="setting", choices="'a', 'b', 'c'")
```

## Example: Minimal App

Here's a complete minimal example:

```bash
# Create structure
mkdir -p handlers/minimal workflows/minimal tests/minimal

# Handler
cat > handlers/minimal/__init__.py << 'EOF'
from .minimal import Minimal
__all__ = ["Minimal"]
EOF

cat > handlers/minimal/minimal.py << 'EOF'
import subprocess
class Minimal:
    def get_version(self):
        try:
            r = subprocess.run(["echo", "1.0"], capture_output=True, text=True)
            return r.stdout.strip()
        except:
            return None
EOF

# Workflow
cat > workflows/minimal/__init__.py << 'EOF'
from .base_workflow import MinimalWorkflow
__all__ = ["MinimalWorkflow"]
EOF

cat > workflows/minimal/base_workflow.py << 'EOF'
from handlers.minimal import Minimal
from harness.workflows.base import Workflow, WorkflowResult
class MinimalWorkflow(Workflow):
    def version(self, item_id="minimal.version"):
        h = Minimal()
        v = h.get_version()
        return WorkflowResult(success=v is not None, item_id=item_id, summary=f"v={v}")
EOF

# Test
cat > tests/minimal/test_version.py << 'EOF'
from workflows.minimal import MinimalWorkflow
class TestMinimal:
    def test_version(self, artifacts):
        w = MinimalWorkflow(artifacts=artifacts)
        r = w.version()
        assert r.success
EOF

# Run
./pytest.sh minimal
```

## Best Practices

1. **Keep handlers thin** - Just wrap CLI/API calls, no test logic
2. **Keep workflows focused** - Orchestrate operations, handle retries, save artifacts
3. **Use artifacts** - Save important state, screenshots, logs for debugging
4. **Make tests resumable** - For tests that might be interrupted, use `persist_state`/`load_persisted_state`
5. **Handle failures gracefully** - Return `WorkflowResult` with failure info, don't crash
6. **Use markers** - Tag tests with appropriate markers (gui, cli, reboot, etc.)
7. **Follow existing patterns** - Look at `system76-power` implementation for guidance
