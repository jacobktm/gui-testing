from ollama import Client
import threading
import time

from ..config import ollama_config

__all__ = ["Ollama"]

# Global queue to serialize requests across all Ollama instances
_queue_lock = threading.Lock()
_last_request_time = 0.0
_min_interval = 0.5  # minimum seconds between requests to avoid overwhelming server


class Ollama:
    def __init__(self):
        ollama_conf = ollama_config()
        self.ip = ollama_conf.get("REMOTE_OLLAMA_IP", None)
        self.port = ollama_conf.get("REMOTE_OLLAMA_PORT", None)
        self.model = ollama_conf.get("model", None)
        self.options = {"num_ctx": 32768}
        self.client = None

    def connect(self):
        if self.client:
            return
        if not self.ip or not self.port:
            print("ERROR: No IP or port.")
            return
        self.client = Client(host=f"http://{self.ip}:{self.port}")

    def send_message(self, content: str, images: list = []):
        global _last_request_time
        if not self.model:
            print("ERROR: No model.")
            return None
        if not self.client:
            print("ERROR: Not connected!!")
            return None
        
        with _queue_lock:
            now = time.time()
            wait_time = _min_interval - (now - _last_request_time)
            if wait_time > 0:
                time.sleep(wait_time)
            msg = {"role": "user",
                   "content": content,
                   "images": images}
            try:
                response = self.client.chat(model=self.model, messages=[msg], options=self.options)
                _last_request_time = time.time()
                if response and "message" in response and "content" in response["message"]:
                    return response["message"]["content"]
                return None
            except Exception as e:
                print(f"ERROR: Ollama request failed: {e}")
                _last_request_time = time.time()
                return None

if __name__ == "__main__":
    ollama = Ollama()
    ollama.connect()
    r = ollama.send_message("Can you see what power profile is active on this system from this screenshot? Give me the response in just a single word, either 'battery', 'balanced', or 'performance'",
                        ["/home/system76/Pictures/Screenshots/Screenshot_2026-10-20_13-03-48.png"])
    print(r)
