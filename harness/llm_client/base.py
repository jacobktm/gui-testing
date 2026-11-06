"""Shared LLM client interface and request pacing.

Every provider client (Ollama, Strata, ...) implements the same surface so
callers (GuiDriver, Set-of-Mark, workflows) never need provider-specific
knowledge:

    client = get_llm_client()   # factory picks the provider from config
    text = client.send_message(prompt, ["/path/to/image.png"])

Contract: ``send_message`` returns the model's reply text, or ``None`` on
any failure. Callers rely on ``None`` to retry/reprompt, so implementations
print diagnostics but must not raise.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

__all__ = ["LlmClient", "request_slot"]

# Global queue to serialize requests across all client instances.
_queue_lock = threading.Lock()
_last_request_time = 0.0
_min_interval = 0.5  # minimum seconds between requests to avoid overwhelming server


@contextmanager
def request_slot():
    """Hold the pacing lock for one provider request.

    Waits until at least ``_min_interval`` has elapsed since the previous
    request completed, then marks completion on exit (success or failure).
    """
    global _last_request_time
    with _queue_lock:
        wait_time = _min_interval - (time.time() - _last_request_time)
        if wait_time > 0:
            time.sleep(wait_time)
        try:
            yield
        finally:
            _last_request_time = time.time()


class LlmClient:
    """Base class for LLM vision servers.

    Attributes:
        model: configured model name, or ``None`` if unset.
        client: connected transport handle, or ``None`` if not connected.
            Callers use ``client`` truthiness as the "connected" check.
    """

    def __init__(self):
        self.model = None
        self.client = None

    def connect(self):
        """Establish the transport handle (``self.client``). Idempotent."""
        raise NotImplementedError

    def send_message(self, content: str, images: list | None = None,
                     options: dict | None = None) -> str | None:
        """Send one chat request with optional image file paths.

        ``options`` is a provider-specific passthrough (e.g. Ollama's
        ``num_ctx``); providers document what they honor.
        """
        raise NotImplementedError
