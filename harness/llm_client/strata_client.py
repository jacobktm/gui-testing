"""Strata provider client (OpenAI-compatible /v1/chat/completions).

Strata is a llama.cpp-based local server exposing an OpenAI-compatible API.
The endpoint shape used here (``http://HOST:PORT/v1/chat/completions``)
follows the llama.cpp server convention; confirm it against your Strata
deployment. Vision requires a multimodal GGUF with its mmproj loaded
server-side.

Unlike the ollama SDK, no library handles images here: this client
base64-encodes image file paths into OpenAI ``image_url`` content parts.
llama.cpp context size is set at server startup, so there is no per-request
equivalent of Ollama's ``num_ctx``; the ``options`` passthrough is ignored.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from ..config import strata_config
from .base import LlmClient, request_slot

__all__ = ["StrataClient"]

_DEFAULT_TIMEOUT = 120.0

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


class StrataClient(LlmClient):
    def __init__(self):
        super().__init__()
        conf = strata_config()
        self.host = conf.get("host", None)
        self.port = conf.get("port", None)
        self.api_key = conf.get("api_key", None)
        self.model = conf.get("model", None)
        self.timeout = float(conf.get("timeout", _DEFAULT_TIMEOUT))

    def connect(self):
        if self.client:
            return
        if not self.host or not self.port:
            print("ERROR: No Strata host or port.")
            return
        # The handle is the completions URL; truthy = connected.
        self.client = f"http://{self.host}:{self.port}/v1/chat/completions"

    @staticmethod
    def _image_data_uri(path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        mime = _MIME_TYPES.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{data}"

    def send_message(self, content: str, images: list | None = None,
                     options: dict | None = None):
        if not self.model:
            print("ERROR: No model.")
            return None
        if not self.client:
            print("ERROR: Not connected!!")
            return None

        parts = [{"type": "text", "text": content}]
        for image in images or []:
            try:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": self._image_data_uri(str(image))},
                })
            except Exception as e:
                print(f"ERROR: Strata: failed to read image {image}: {e}")
                return None

        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": parts}],
        }).encode("utf-8")
        req = urllib.request.Request(
            self.client,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            with request_slot():
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            content_out = body["choices"][0]["message"]["content"]
            if content_out is None:
                return None
            return str(content_out)
        except Exception as e:
            print(f"ERROR: Strata request failed: {e}")
            return None
