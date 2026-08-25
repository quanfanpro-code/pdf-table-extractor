import json
from pathlib import Path

from app.config import ModelSettings
from app.extractors import ai_vision
from app.extractors.ai_vision import (
    check_model_capabilities,
    load_progress,
    request_page,
    safe_request_error,
    save_progress,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


def test_request_uses_user_url_model_and_key(monkeypatch):
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": "|交易时间|\n|---|"}}]})

    monkeypatch.setattr(ai_vision.requests, "post", fake_post)
    settings = ModelSettings(
        "https://example.com/v1/chat/completions",
        "vision-x",
        "secret-key",
    )

    request_page(b"image-bytes", settings, prompt="提取表格")

    assert captured["url"] == settings.api_url
    assert captured["json"]["model"] == "vision-x"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["messages"][0]["content"][1]["type"] == "image_url"


def test_request_allows_blank_api_key(monkeypatch):
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": "成功"}}]})

    monkeypatch.setattr(ai_vision.requests, "post", fake_post)
    request_page(
        b"image-bytes",
        ModelSettings("http://127.0.0.1:1234/v1/chat/completions", "local-vision"),
        prompt="测试",
    )

    assert "Authorization" not in captured["headers"]


def test_error_message_does_not_echo_api_key():
    settings = ModelSettings("https://example.com", "vision-x", "very-secret-key")

    message = safe_request_error(RuntimeError("very-secret-key refused"), settings)

    assert "very-secret-key" not in message
    assert "***" in message


def test_progress_rejects_changed_source_pdf(tmp_path):
    pdf_path = tmp_path / "样本.pdf"
    progress_path = tmp_path / "progress.json"
    pdf_path.write_bytes(b"first-version")
    save_progress(progress_path, pdf_path, current_page=2, header=["交易时间"], rows=[])

    assert load_progress(progress_path, pdf_path)["current_page"] == 2

    pdf_path.write_bytes(b"changed-version")

    assert load_progress(progress_path, pdf_path) is None


def test_capability_check_accepts_missing_models_endpoint_when_chat_works(monkeypatch):
    def fake_get(**kwargs):
        return FakeResponse({"error": "not supported"}, status_code=404)

    def fake_post(**kwargs):
        return FakeResponse({"choices": [{"message": {"content": "成功"}}]})

    monkeypatch.setattr(ai_vision.requests, "get", fake_get)
    monkeypatch.setattr(ai_vision.requests, "post", fake_post)

    report = check_model_capabilities(
        ModelSettings("https://example.com/v1/chat/completions", "vision-x", "secret")
    )

    assert report.endpoint_reachable is True
    assert report.model_callable is True
    assert report.vision_capable is True
    assert report.models_endpoint_available is False


def test_failed_page_is_not_marked_as_completed_for_resume(monkeypatch, tmp_path):
    class FakeDocument:
        def __init__(self, _path):
            pass

        def __len__(self):
            return 2

        def close(self):
            pass

    responses = iter(
        [
            """银行名称：测试银行
账号：00001234
账单交易笔数：1
账单借方合计：0.00
账单贷方合计：100.00
|交易时间|摘要|凭证类型|凭证号码|借方发生额|贷方发生额|账户余额|流水号|对方户名/账号|对方行名|
|---|---|---|---|---|---|---|---|---|---|
|2026/01/02 09:30:00|收款|网银|0001|0.00|100.00|100.00|12345678901234567890|测试公司/123|测试银行|
""",
            RuntimeError("暂时断网"),
        ]
    )

    def fake_request(*_args, **_kwargs):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ai_vision.pdfium, "PdfDocument", FakeDocument)
    monkeypatch.setattr(ai_vision, "_render_page", lambda *_args: b"image")
    monkeypatch.setattr(ai_vision, "request_page", fake_request)
    pdf_path = tmp_path / "断点样本.pdf"
    pdf_path.write_bytes(b"pdf-placeholder")

    extraction = ai_vision.extract_ai(
        pdf_path,
        ModelSettings("https://example.com/v1/chat/completions", "vision-x"),
    )
    progress = json.loads(Path(str(pdf_path) + ".ai-progress.json").read_text(encoding="utf-8"))

    assert len(extraction.transactions) == 1
    assert progress["current_page"] == 1
    assert progress["completed"] is False
