import json
import os
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

# ---------- Типы ----------
KeepAliveTime = Literal["1m", "5m", "10m", "1h", "2h", 0, -1]

class OllamaOptions(TypedDict, total=False):
    temperature: float
    num_predict: int
    num_ctx: int

@dataclass
class AppConfig:
    ollama_api_url: str
    models: list[str]
    keep_alive: KeepAliveTime
    options: OllamaOptions

# ---------- Загрузка ----------
def _default_json_path() -> str:
    # Ищем config.json в app/llm/
    base_dir = os.path.dirname(os.path.abspath(__file__)) 
    return os.path.join(base_dir, "llm", "config.json")

def load_config(
    config_path: str | None = None,
    env: dict[str, str] | None = None,
) -> AppConfig:
    if config_path is None:
        config_path = _default_json_path()
    if env is None:
        env = os.environ

    # Читаем JSON
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    # Извлекаем параметры
    options = {
        "temperature": config_data.get("temperature", 0.1),
        "num_predict": config_data.get("num_predict", 4096),
        "num_ctx": config_data.get("num_ctx", 8192)
    }

    models_raw = env.get("MODELS", "deepseek-r1:14b")
    models = [m.strip() for m in models_raw.split(",") if m.strip()]
    
    if not models:
        raise ValueError("MODELS is empty. Set MODELS in .env")

    return AppConfig(
        ollama_api_url=env.get("OLLAMA_API_URL", "http://localhost:11434/api/chat"),
        models=models,
        keep_alive=cast(KeepAliveTime, config_data.get("keep_alive", 0)),
        options=cast(OllamaOptions, options)
    )