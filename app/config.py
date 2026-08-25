import json
from dataclasses import asdict, dataclass
from pathlib import Path


APP_CONFIG_DIR = Path.home() / ".pdf_table_extractor"
APP_CONFIG_FILE = APP_CONFIG_DIR / "config.json"
DEFAULT_API_KEY_FILE = APP_CONFIG_DIR / "api_key.txt"


@dataclass(slots=True)
class ModelSettings:
    api_url: str
    model_name: str
    api_key: str = ""


@dataclass(slots=True)
class AppConfig:
    api_url: str = ""
    model_name: str = ""
    api_key_file_path: str = ""
    force_ai_mode: bool = False


def normalize_chat_url(base_or_url: str) -> str:
    value = (base_or_url or "").strip().rstrip("/")
    if not value:
        return ""
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"


def build_models_url(base_or_url: str) -> str:
    chat_url = normalize_chat_url(base_or_url)
    if not chat_url:
        return ""
    return chat_url[: -len("chat/completions")] + "models"


def load_app_config(path: Path = APP_CONFIG_FILE) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return AppConfig()

    if "api_url" in raw or "model_name" in raw:
        return AppConfig(
            api_url=str(raw.get("api_url", "")).strip(),
            model_name=str(raw.get("model_name", "")).strip(),
            api_key_file_path=str(raw.get("api_key_file_path", "")).strip(),
            force_ai_mode=bool(raw.get("force_ai_mode", False)),
        )

    local_mode = "本地" in str(raw.get("llm_mode", ""))
    return AppConfig(
        api_url=str(raw.get("local_base_url", "")).strip() if local_mode else "",
        model_name=str(raw.get("local_model" if local_mode else "cloud_model", "")).strip(),
        api_key_file_path=str(raw.get("api_key_file_path", "")).strip(),
        force_ai_mode=bool(raw.get("force_ai_mode", False)),
    )


def save_app_config(config: AppConfig, path: Path = APP_CONFIG_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_api_key(api_key: str, path: Path = DEFAULT_API_KEY_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(api_key.strip(), encoding="utf-8")
    return path
