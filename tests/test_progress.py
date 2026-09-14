from app.progress import progress_scope, report_progress


def test_progress_context_restored_after_failure():
    events = []
    try:
        with progress_scope(events.append):
            report_progress("inside")
            raise ValueError("expected")
    except ValueError:
        pass
    report_progress("outside")
    assert events == ["inside"]


def test_model_reports_page_wait_save_and_resume(tmp_path, monkeypatch):
    from app.extractors import ai_vision
    from app.config import ModelSettings
    from test_text_align import statement_pdf
    path = statement_pdf(tmp_path / "two-pages.pdf", pages=[[], []])
    events = []
    monkeypatch.setattr(ai_vision, "_render_page", lambda *args: b"test")
    monkeypatch.setattr(ai_vision, "request_page", lambda *args: "账单交易笔数：0\n账单借方合计：0.00\n账单贷方合计：0.00")
    with progress_scope(events.append):
        ai_vision.extract_ai(path, ModelSettings("https://example.invalid/v1", "test"))
    assert ["第 1/2 页" in events[0], "等待模型返回" in events[0], "已保存" in events[1], "第 2/2 页" in events[2]] == [True] * 4
    def must_not_call(*args):
        raise AssertionError("Resume should use completed pages")
    monkeypatch.setattr(ai_vision, "request_page", must_not_call)
    e = ai_vision.extract_ai(path, ModelSettings("https://example.invalid/v1", "test"))
    assert e.page_count == 2


def test_forced_model_still_skips_local(monkeypatch):
    from pathlib import Path
    from app import routing
    from app.config import ModelSettings
    from test_services import make_extraction
    def must_not_list():
        raise AssertionError("Force mode must not run local extractors")
    monkeypatch.setattr(routing, "iter_local_extractors", must_not_list)
    monkeypatch.setattr(routing, "extract_ai", lambda path, settings: make_extraction(path))
    assert routing.process_pdf(Path("force.pdf"), ModelSettings("https://example.invalid", "test"), force_ai=True).validation.status == "通过"
