# Workflows Documentation

Workflows are the high-level orchestration layer for test operations. They combine handlers and harness primitives to implement test logic.

## Base Classes

### Workflow

Located in `harness.workflows.base`:

```python
from harness.workflows.base import Workflow, WorkflowResult

class Workflow:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts
    
    def run(self, *args, **kwargs) -> WorkflowResult:
        raise NotImplementedError
    
    def resume_progress(self, item_id: str, *, kind: str, phase: str = "state") -> dict:
        # Load persisted state if it matches the expected kind
        ...
    
    def persist_state(self, item_id: str, phase: str, state: dict, *, step: str = "state"):
        # Save state to artifacts
        ...
    
    def load_persisted_state(self, item_id: str, phase: str = "state") -> dict | None:
        # Load state from artifacts
        ...
```

### WorkflowResult

```python
@dataclass
class WorkflowResult:
    success: bool
    item_id: str | None = None
    summary: str = ""
    data: dict[str, Any] | None = None
```

All workflow methods should return `WorkflowResult` objects.

## Generic Workflows

### UIWorkflow

Located in `harness.workflows.ui_workflow`. Provides generic UI interaction patterns:

```python
from harness.workflows import UIWorkflow

ui = UIWorkflow(artifacts=artifacts)
```

#### Methods

**`open_ui_elements(clicks, delay_between=2.0, item_id=None)`**
Click through a sequence of coordinates to open UI elements.

```python
result = ui.open_ui_elements([(0.1, 0.1), (0.2, 0.2)], delay_between=3.0)
```

**`take_screenshot(os_id=None, item_id=None, out_dir="/tmp/opencode/gui")`**
Take a screenshot.

```python
result = ui.take_screenshot()
path = result.data["path"]
```

**`query_llm(prompt, image_path, expected=None, item_id=None)`**
Query LLM with an image and optional expected values for parsing.

```python
result = ui.query_llm(prompt, image_path, expected={"on", "off"})
if result.success:
    value = result.data["value"]
```

**`detect_from_ui(clicks, prompt, expected, os_id=None, delay_between_clicks=2.0, wait_after_clicks=5.0, item_id=None, max_attempts=5)`**
Full chain: click UI elements → wait → screenshot → crop → query LLM. With retries.

```python
result = ui.detect_from_ui(
    clicks=[(0.5, 0.1), (0.5, 0.3)],
    prompt="What setting is selected?",
    expected={"enabled", "disabled"},
    max_attempts=5
)
```

## App-Specific Workflows

App-specific workflows live in `workflows/<app>/`. For system76-power, see `workflows/system76_power/`.

### System76PowerWorkflow (base)

Common operations for system76-power:
- `check_profile()` - Query current power profile
- `check_brightness()` - Check brightness level

### System76PowerCLIWorkflow

CLI-focused operations:
- `query_profile()` - Query and record profile
- `set_profile()` / profile transitions via CLI
- `check_brightness_after_reboot()` - Verify brightness preserved across reboot

### System76PowerGUIWorkflow

GUI-focused operations using vision:
- Navigate to power/graphics settings
- Click to change profiles/graphics modes
- Validate changes

### ProfileTransitionWorkflow

High-level orchestration for power profile transitions:
- Works with both GUI and CLI
- Validates state via UI
- Handles different desktop environments

```python
from workflows.system76_power import ProfileTransitionWorkflow

wf = ProfileTransitionWorkflow(artifacts=artifacts)
result = wf.transition_to("balanced", os_id="pop-24.04", via="gui")
```

### GraphicsTransitionWorkflow

Similar for graphics mode transitions (Pop!_OS specific).

## State Persistence

For tests that need to survive reboots or resume:

```python
class MyWorkflow(Workflow):
    def do_something(self, item_id):
        # Check for saved progress
        progress = self.resume_progress(item_id, kind="my_step")
        if progress.get("done"):
            return WorkflowResult(success=True, summary="already done")
        
        # Do work
        ...
        
        # Save progress
        self.persist_state(item_id, "progress", {
            "kind": "my_step",
            "done": True,
            "data": {...}
        })
```

## Best Practices

1. **Always return WorkflowResult** - Don't raise exceptions from workflow methods; catch and return failure results
2. **Use artifacts** - Save screenshots, logs, and important data for debugging
3. **Make methods idempotent when possible** - Helps with resume/retry
4. **Accept artifacts in __init__** - Pass through to base class
5. **Use item_id for tracking** - Enables manifest tracking and resume
6. **Compose, don't duplicate** - Use UIWorkflow, GuiDriver, handlers rather than reimplementing
7. **Handle timeouts** - GUI operations need sleeps/waits; be generous
8. **Validate inputs** - Check OS compatibility, skip if not applicable
