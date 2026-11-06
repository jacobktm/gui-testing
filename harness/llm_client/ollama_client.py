"""Ollama provider client (native /api/chat via the ollama SDK)."""

from ollama import Client

from ..config import ollama_config
from .base import LlmClient, request_slot

__all__ = ["OllamaClient"]

# Requests time out instead of hanging the suite forever; the ollama SDK
# passes this through to httpx.
_DEFAULT_TIMEOUT = 120.0


class OllamaClient(LlmClient):
    def __init__(self):
        super().__init__()
        ollama_conf = ollama_config()
        self.ip = ollama_conf.get("REMOTE_OLLAMA_IP", None)
        self.port = ollama_conf.get("REMOTE_OLLAMA_PORT", None)
        self.model = ollama_conf.get("model", None)
        self.timeout = float(ollama_conf.get("timeout", _DEFAULT_TIMEOUT))
        self.options = {"num_ctx": 32768}

    def connect(self):
        if self.client:
            return
        if not self.ip or not self.port:
            print("ERROR: No IP or port.")
            return
        self.client = Client(host=f"http://{self.ip}:{self.port}",
                             timeout=self.timeout)

    def send_message(self, content: str, images: list | None = None,
                     options: dict | None = None):
        if not self.model:
            print("ERROR: No model.")
            return None
        if not self.client:
            print("ERROR: Not connected!!")
            return None

        # The SDK base64-encodes image file paths itself.
        msg = {"role": "user",
               "content": content,
               "images": list(images or [])}
        try:
            with request_slot():
                response = self.client.chat(
                    model=self.model,
                    messages=[msg],
                    options=options or self.options,
                )
            if response and "message" in response and "content" in response["message"]:
                return response["message"]["content"]
            return None
        except Exception as e:
            print(f"ERROR: Ollama request failed: {e}")
            return None
