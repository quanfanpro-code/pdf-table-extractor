def test_app_package_can_be_imported():
    import app

    assert app.__all__ == []


def test_main_exposes_start_function():
    import main

    assert callable(main.main)


def test_ui_uses_generic_model_fields():
    from pathlib import Path

    source = Path("app/ui.py").read_text(encoding="utf-8")

    assert "接口地址" in source
    assert "API Key" in source
    assert "模型名称" in source
    assert "百炼" not in source
    assert "千问" not in source
