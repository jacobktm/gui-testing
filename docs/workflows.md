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
- `transition_graphics(source, target)` - Switch graphics mode, reboot, then
  verify. On flavors where `supports_graphics_switching()` is true (Pop!_OS
  22.04), the transition must *also* be visually confirmed: the panel applet
  is opened and the mode read back from a screenshot
  (`_gui_verify_graphics_mode`). Any visual failure (open, capture, or a
  mismatch) fails the transition — `gui_verified=None` only means the flavor
  has no such UI. Detection screenshots land under `<item_id>.gui`.

### System76PowerGUIWorkflow

GUI-focused operations using vision:
- Navigate to power/graphics settings
- Click to change profiles/graphics modes
- Validate changes

### ProfileTransitionWorkflow

UI validation of power profiles (clicks → screenshot → LLM):
- `validate_profile(target, os_id, item_id)` — open the panel, detect the
  selected profile, and check it equals *target*
- exposes `gui_wf` / `ui` so tests can drive the GUI workflow directly

```python
from workflows.system76_power import ProfileTransitionWorkflow

wf = ProfileTransitionWorkflow(artifacts=artifacts)
result = wf.validate_profile("balanced", os_id="pop-24.04")
```

### Graphics transitions — one shared phase machine

CLI and GUI graphics transitions run through the *same* reboot-aware phase
machine: `GraphicsTransitionMixin` in
`workflows/system76_power/graphics_transitions.py` (`GRAPHICS_CHAIN_ORDER`
is a **closed** circuit over all 12 directed edges — every mode's out-degree
and in-degree match, the walk returns to its start). Because it is closed,
`get_graphics_chain()` **rotates** it at collection to start from whatever
mode the machine is actually in — no priming `to_hybrid` test (and its extra
reboot) is needed. The rotation is persisted
(`~/.local/share/gui-testing/graphics_chain.json`) and reused on resumed
boots: re-rotating mid-run would move the edge whose reboot is in flight off
the front of the chain. The drivers differ only in two hooks: how the mode is
switched (`system76-power` vs panel clicks) and how the desktop is visually
verified. Phases (`start` → `rebooting` → `done`) are persisted per `item_id`,
so a test resumes on the boot after the reboot and idempotently replays
completed edges.

**Reboot path after a mode switch** (`_reboot_after_switch` hook): the CLI
(default) settles 10 s (30 s for `integrated`, which powers the dGPU off),
enables autologin, and issues the scripted reboot chain. Pop!_OS 22.04 *GUI*
transitions override this: the shell modal that the extension raises after a
mode change performs the reboot itself — the harness waits ≥ 90 s for the
asynchronous switch to finish, then activates the modal's "Reboot Now" button
with **Tab, Tab, Enter** (hardware-verified; no coordinates needed). Forcing
`reboot -f` while the switch is still in flight corrupts the system, and the
modal cannot fire before the system says it is ready. The current boot ID is
marked before the keys go out, so `wait_for_boot` confirms the new boot
whoever initiated the reboot; if the modal never produces one, the scripted
reboot path takes over as a fallback.

Tests are parametrized over the (rotated) chain (one test per edge, in chain
order):

- CLI: `test_graphics_transition[source_to_target]` keeps **per-transition**
  item ids (`cli.graphics_transition.<s>_to_<t>`).
- GUI: `test_gui_graphics_transition[<s>_to_<t>]` deliberately shares one
  item id (`gui.graphics_transitions`) whose state document accumulates all
  twelve results — the pre-parametrization scheme; don't mix the two.
- Power-profile transitions use the same idea with a closed 6-edge circuit
  over the three profiles (`PERF_PROFILE_CIRCUIT` + `get_perf_profile_chain()`
  rotated to the current profile). Profile switches never reboot, so nothing
  is persisted — each transition sets/verifies its *target*, so a
  mid-run source mismatch is harmless.
- Flavor gating is capability-based (`supports_graphics_switching()`), never
  `os_id.startswith(...)`.

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
