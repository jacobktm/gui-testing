"""Provider factory: pick the configured LLM client and connect it."""

from __future__ import annotations

from ..config import llm_config
from .ollama_client import OllamaClient
from .strata_client import StrataClient

__all__ = ["get_llm_client"]


def get_llm_client() -> OllamaClient | StrataClient:
    """Build the LLM client for the configured provider.

    Reads the ``llm`` config section (provider + per-provider settings,
    with legacy top-level ``ollama`` fallback). An unknown provider value
    loudly falls back to Ollama rather than silently misbehaving.
    """
    provider = llm_config().get("provider", "ollama")
    if provider == "strata":
        client = StrataClient()
    elif provider == "ollama":
        client = OllamaClient()
    else:
        print(f"ERROR: Unknown LLM provider {provider!r}; using ollama.")
        client = OllamaClient()
    try:
        client.connect()
    except Exception as e:
        print(f"ERROR: LLM connect failed: {e}")
    return client
