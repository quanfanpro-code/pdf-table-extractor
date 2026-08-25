from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.config import ModelSettings
from app.models import ProcessedStatement, StatementExtraction, Transaction, ValidationReport
from app import routing, services


MODEL_SETTINGS = ModelSettings("https://example.com/v1/chat/completions", "vision-x")


def make_extraction(path: Path, valid: bool = True, period_start: date = date(2026, 1, 1)):
    transaction = Transaction(
        occurred_at=datetime.combine(period_start, datetime.min.time()),
        summary="测试",
        voucher_type="网银",
        voucher_number="0001",
        debit=Decimal("0.00"),
        credit=Decimal("100.00"),
        balance=Decimal("100.00"),
        serial_number="12345678901234567890",
        counterparty="测试公司",
        counterparty_bank="测试银行",
        bank_name="测试银行",
        account_number="00001234",
        period_start=period_start,
        period_end=period_start,
        source_file=path.name,
        source_page=1,
        extraction_method="测试",
    )
    return StatementExtraction(
        source_path=path,
        bank_name="测试银行",
        account_number="00001234",
        period_start=period_start,
        period_end=period_start,
        page_count=1,
        extraction_method="测试",
        transactions=[transaction],
        declared_count=1 if valid else 2,
        declared_debit=Decimal("0.00"),
        declared_credit=Decimal("100.00"),
    )


def test_text_failure_can_fall_back_to_ai(monkeypatch):
    calls = []

    def no_result(label):
        def extractor(_path):
            calls.append(label)
            return None

        return extractor

    monkeypatch.setattr(routing, "extract_generic_table", no_result("普通表格"))
    monkeypatch.setattr(routing, "extract_minsheng", no_result("民生银行"))
    monkeypatch.setattr(routing, "extract_huaxia", no_result("华夏银行"))

    def ai_result(path, _settings):
        calls.append("AI")
        return make_extraction(path)

    monkeypatch.setattr(routing, "extract_ai", ai_result)

    result = routing.process_pdf(Path("样本.pdf"), MODEL_SETTINGS)

    assert calls == ["普通表格", "民生银行", "华夏银行", "AI"]
    assert result.validation.status == "通过"


def test_missing_model_settings_is_reported_instead_of_silently_skipped(monkeypatch):
    monkeypatch.setattr(routing, "extract_generic_table", lambda _path: None)
    monkeypatch.setattr(routing, "extract_minsheng", lambda _path: None)
    monkeypatch.setattr(routing, "extract_huaxia", lambda _path: None)

    result = routing.process_pdf(Path("无法读取.pdf"), None)

    assert result.validation.status == "核对失败"
    assert any("模型" in message for message in result.validation.errors)


def test_failed_file_is_not_in_approved_transactions(monkeypatch):
    paths = [Path("通过.pdf"), Path("失败.pdf")]

    def fake_process(path, _settings, force_ai=False):
        extraction = make_extraction(path)
        status = "通过" if path.name == "通过.pdf" else "核对失败"
        return ProcessedStatement(
            source_path=path,
            extraction=extraction,
            validation=ValidationReport(
                status=status,
                actual_count=1,
                actual_debit=Decimal("0.00"),
                actual_credit=Decimal("100.00"),
                errors=[] if status == "通过" else ["测试失败"],
            ),
        )

    monkeypatch.setattr(services, "process_pdf", fake_process)

    batch = services.process_batch(paths, None, force_ai=False)

    assert len(batch.approved_transactions) == 1
    assert batch.approved_transactions[0].source_file == "通过.pdf"
    assert next(item for item in batch.statements if item.source_path.name == "失败.pdf").validation.status == "核对失败"


def test_scan_pdf_files_includes_subfolders_and_skips_output_folder(tmp_path):
    (tmp_path / "甲.pdf").write_bytes(b"pdf")
    subfolder = tmp_path / "子目录"
    subfolder.mkdir()
    (subfolder / "乙.PDF").write_bytes(b"pdf")
    output = tmp_path / "提取结果"
    output.mkdir()
    (output / "旧结果.pdf").write_bytes(b"pdf")

    result = services.scan_pdf_files(tmp_path)

    assert {path.name for path in result} == {"甲.pdf", "乙.PDF"}


def test_batch_statements_sort_by_period(monkeypatch):
    paths = [Path("二月.pdf"), Path("一月.pdf")]

    def fake_process(path, _settings, force_ai=False):
        period = date(2026, 2, 1) if path.name == "二月.pdf" else date(2026, 1, 1)
        extraction = make_extraction(path, period_start=period)
        return ProcessedStatement(
            source_path=path,
            extraction=extraction,
            validation=ValidationReport(
                status="通过",
                actual_count=1,
                actual_debit=Decimal("0.00"),
                actual_credit=Decimal("100.00"),
            ),
        )

    monkeypatch.setattr(services, "process_pdf", fake_process)

    batch = services.process_batch(paths, None, force_ai=False)

    assert [item.source_path.name for item in batch.statements] == ["一月.pdf", "二月.pdf"]
