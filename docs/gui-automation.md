# GUI Automation

This document covers vision-based GUI automation using Set-of-Mark, screenshots, and LLMs.

## Overview

The framework uses a vision-first approach:
1. Capture screenshot of the screen
2. Detect UI elements using OpenCV
3. Annotate elements with numeric labels (Set-of-Mark)
4. Ask a multimodal LLM which label corresponds to the target
5. Convert to screen coordinates and click with dotool

This works across different desktop environments without relying on accessibility APIs.

## Components

### GuiDriver (`harness.gui.driver`)

Main interface for GUI automation:

```python
from harness.gui import GuiDriver

driver = GuiDriver(artifacts=artifacts)
```

**Methods:**
- `go_to(coords)` - Move mouse to normalized coordinates (0-1)
- `click_at(coords)` - Move and click
- `detect_coords_som(target_description, ...)` - Find element coordinates via SoM
- `detect_power_profile_som(os_id, target=None, ...)` - Detect active power profile
- `capture_and_detect(...)` - Full capture and detection flow

### Set-of-Mark (`harness.gui.set_of_mark`)

Implements element detection and annotation:

```python
from harness.gui.set_of_mark import generate_set_of_mark, detect_element_coords
```

- `generate_set_of_mark(image_path)` - Detect UI elements and create annotated image with labels
- `detect_element_coords(image_path, target_description, ollama_ip, ollama_port, ollama_model)` - Get coordinates for target

### Screenshots (`harness.screenshots`)

```python
from harness.screenshots import capture, crop_active_display
```

- `capture(path)` - Take screenshot using configured backend
- `crop_active_display(screenshot, output_path)` - Crop to active display

Screenshot backends are selected based on desktop environment:
- `cosmic-screenshot` for COSMIC
- `gnome-dotool` for GNOME (uses Shift+Print)

### Dotool (`harness.dotool`)

Input injection:

```python
from harness.dotool import click, mouseto, type_text, key
```

Works on both X11 and Wayland via uinput.

### Coordinates (`harness.gui.coords`)

Coordinate handling and scaling:

```python
from harness.gui import Coords
from harness.gui.coords import adjust_coords, get_display_resolution, COORD_SOURCE
```

- `Coords` - Predefined coordinates for system76-power UI elements
- `adjust_coords(coords, src_res, dst_res)` - Scale coordinates between resolutions
- `get_display_resolution()` - Get current display resolution
- `COORD_SOURCE` - Source resolutions for predefined coordinates

## Set-of-Mark Flow

### 1. Element Detection

OpenCV detects UI elements (buttons, clickable regions, etc.) and assigns numeric IDs.

### 2. Annotation

The annotated image shows numbered boxes/labels over detected elements.

### 3. LLM Query

The LLM is asked to identify which numbered element matches the description:

```
Which numbered element in this image is the "Power Mode" dropdown?
Answer with just the number.
```

### 4. Coordinate Extraction

The center of the selected element's bounding box is converted to normalized coordinates (0-1) and returned.

## Usage Patterns

### Find and Click an Element

```python
driver = GuiDriver(artifacts=artifacts)
coords = driver.detect_coords_som("the Balanced power profile option")
if coords:
    driver.click_at(coords)
```

### Using UIWorkflow

```python
from harness.workflows import UIWorkflow

ui = UIWorkflow(artifacts=artifacts)
result = ui.detect_from_ui(
    clicks=[(0.1, 0.05), (0.3, 0.2)],  # Open Settings, navigate
    prompt="Which power profile is currently selected? Answer: performance, balanced, or battery",
    expected={"performance", "balanced", "battery"},
    wait_after_clicks=8.0,
)
if result.success:
    print(result.data["value"])
```

### Custom Detection

```python
from harness.gui.set_of_mark import detect_element_coords

coords = detect_element_coords(
    "/tmp/screenshot.png",
    "the Apply button",
    ollama_ip="localhost",
    ollama_port="11434",
    ollama_model="qwen3-vl:8b"
)
```

## Configuration

### Ollama

Configure in `config.json`:
```json
{
  "ollama": {
    "REMOTE_OLLAMA_IP": "192.168.1.100",
    "REMOTE_OLLAMA_PORT": "11434",
    "model": "qwen3-vl:8b"
  }
}
```

### Screenshot Tool

Set in config or auto-detected by `setup.sh`:
```json
{
  "screenshot_tool": "cosmic-screenshot"
}
```

## Tips & Best Practices

1. **Wait after clicks** - UI animations need time; use 2-8 second waits
2. **Crop to active display** - Avoids issues with multiple displays
3. **Retry on failure** - LLM responses can be inconsistent; use retries
4. **Dismiss notifications** - Click center of screen to dismiss screenshot notifications
5. **Use specific descriptions** - "the Balanced radio button" is better than "balanced"
6. **Handle different resolutions** - Use coordinate scaling for predefined coords
7. **Test on target desktop** - SoM behavior can vary slightly between GNOME/COSMIC
8. **Keep prompts simple** - Ask for specific choices, easier to parse

## Troubleshooting

### No elements detected
- Check OpenCV is working
- Ensure screenshot was captured successfully
- Try different element detection parameters

### Wrong element selected
- Make description more specific
- Use clearer prompts
- Check if element is actually visible

### Coordinates off
- Verify display resolution detection
- Check coordinate scaling
- Ensure using correct display

### Ollama issues
- Verify Ollama is running and accessible
- Check model is pulled
- Ensure sufficient GPU memory
- Check network connectivity if remote
