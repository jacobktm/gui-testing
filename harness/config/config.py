import json
from pathlib import Path

__all__ = [
    "llm_config",
    "ollama_config",
    "strata_config",
    "get_screenshot_tool",
]


def _config_path():
    return Path(__file__).resolve().parents[2] / 'config.json'

def llm_config() -> dict:
    """Provider-aware LLM settings: {'provider', 'ollama', 'strata'}.

    The "llm" section names the active provider and holds each provider's
    connection settings:

        "llm": {
          "provider": "ollama",
          "ollama": {"REMOTE_OLLAMA_IP": ..., "REMOTE_OLLAMA_PORT": ..., "model": ...},
          "strata": {"host": ..., "port": ..., "model": ..., "api_key": optional}
        }
    """
    config_path = _config_path()
    if not config_path.exists():
        print("ERROR: config file not found. Please run setup.sh")
        return {'provider': 'ollama', 'ollama': {}, 'strata': {}}
    with open(config_path, 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)
    llm = config.get('llm') or {}
    return {
        'provider': llm.get('provider', 'ollama'),
        'ollama': llm.get('ollama') or {},
        'strata': llm.get('strata') or {},
    }

def ollama_config() -> dict:
    return llm_config()['ollama']

def strata_config() -> dict:
    return llm_config()['strata']

def get_screenshot_tool() -> str | None:
    config_path = _config_path()
    if not config_path.exists():
        return None
    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            config = json.load(config_file)
        tool = config.get('screenshot_tool')
        if isinstance(tool, str):
            tool = tool.strip()
            if tool:
                return tool
    except Exception:
        pass
    return None
