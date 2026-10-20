from ollama import Client

from config import ollama_config

class Ollama:
    def __init__(self):
        ollama_conf = ollama_config()
        self.ip = ollama_conf.get("REMOTE_OLLAMA_IP", None)
        self.port = ollama_conf.get("REMOTE_OLLAMA_PORT", None)
        self.model = ollama_conf.get("model", None)
        self.options = { "num_ctx": 32768 }
        self.client = None

    def connect(self):
        if self.client:
            return
        if not self.ip or not self.port:
            print("ERROR: No IP or port.")
            return
        self.client = Client(host=f"http://{self.ip}:{self.port}")

    def send_message(self, content: str, images: list = []):
        if not self.model:
            print("ERROR: No model.")
            return None
        if not self.client:
            print("ERROR: Not connected!!")
            return None
        msg = { "role": "user",
                "content": content,
                "images": images }
        response = self.client.chat(model=self.model, messages=[msg], options=self.options)
        return response["message"]["content"]

if __name__ == "__main__":
    ollama = Ollama()
    ollama.connect()
    r = ollama.send_message("Can you see what power profile is active on this system from this screenshot? Give me the response in just a single word, either 'battery', 'balanced', or 'performance'",
                        ["/home/system76/Pictures/Screenshots/Screenshot_2026-10-20_13-03-48.png"])
    print(r)
