import json
from pathlib import Path

def ollama_config():
    config = {}
    config_path = Path(__file__).resolve().parent.parent / 'config.json'
    with open(config_path, 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)
    return config.get('ollama', {})
