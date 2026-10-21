import json
from pathlib import Path

def _config_path():
    return Path(__file__).resolve().parent.parent / 'config.json'

def ollama_config():
    config = {}
    config_path = _config_path()
    if not config_path.exists():
        print("ERROR: config file not found. Please run setup.sh")
        return {}
    with open(config_path, 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)
    return config.get('ollama', {})

def set_ollama_ip(ip: str):
    if not ip:
        print("ERROR: No IP address specified.")
        return
    config = {}
    config_path = _config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
    else:
        config["ollama"] = {}
    config["ollama"]["REMOTE_OLLAMA_IP"] = ip
    with open(config_path, 'w', encoding='utf-8') as config_file:
        json.dump(config, config_file, indent=2, ensure_ascii=False)

def set_ollama_port(port: str):
    if not port:
        port = "11434"
    config = {}
    config_path = _config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
    else:
        config["ollama"] = {}
    config["ollama"]["REMOTE_OLLAMA_PORT"] = port
    with open(config_path, 'w', encoding='utf-8') as config_file:
        json.dump(config, config_file, indent=2, ensure_ascii=False)

def set_ollama_model(model: str):
    if not model:
        print("ERROR: No ollama model specified.")
        return
    config = {}
    config_path = _config_path()
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
    else:
        config["ollama"] = {}
    config["ollama"]["model"] = model
    with open(config_path, 'w', encoding='utf-8') as config_file:
        json.dump(config, config_file, indent=2, ensure_ascii=False)

