import json

from app.config import (
    AppConfig,
    build_models_url,
    load_app_config,
    normalize_chat_url,
    save_api_key,
    save_app_config,
)


def test_normalize_chat_url_accepts_base_v1_and_full_url():
    assert normalize_chat_url("https://example.com") == "https://example.com/v1/chat/completions"
    assert normalize_chat_url("https://example.com/v1") == "https://example.com/v1/chat/completions"
    assert normalize_chat_url("https://example.com/v1/chat/completions") == "https://example.com/v1/chat/completions"


def test_build_models_url_uses_same_api_root():
    assert build_models_url("https://example.com/v1/chat/completions") == "https://example.com/v1/models"


def test_legacy_cloud_config_is_migrated_without_provider_default(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "llm_mode": "网络模式（百炼 Qwen3.6）",
                "cloud_model": "old-model",
                "api_key_file_path": "C:/keys/old.txt",
                "force_ai_mode": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_app_config(path)

    assert config.api_url == ""
    assert config.model_name == "old-model"
    assert config.api_key_file_path == "C:/keys/old.txt"
    assert config.force_ai_mode is True


def test_legacy_local_config_migrates_local_address(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "llm_mode": "本地模式（LM Studio）",
                "local_base_url": "http://127.0.0.1:1234",
                "local_model": "local-vision",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_app_config(path)

    assert config.api_url == "http://127.0.0.1:1234"
    assert config.model_name == "local-vision"


def test_main_config_does_not_contain_api_key(tmp_path):
    path = tmp_path / "config.json"
    save_app_config(
        AppConfig(
            api_url="https://example.com",
            model_name="vision-x",
            api_key_file_path="C:/keys/generic.txt",
            force_ai_mode=False,
        ),
        path,
    )

    saved = path.read_text(encoding="utf-8")

    assert "vision-x" in saved
    assert "secret-value" not in saved
    assert "api_key\"" not in saved


def test_api_key_is_saved_to_separate_file(tmp_path):
    key_path = save_api_key("  secret-value  ", tmp_path / "api_key.txt")

    assert key_path.read_text(encoding="utf-8") == "secret-value"
