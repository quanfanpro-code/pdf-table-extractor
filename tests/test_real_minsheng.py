import os
from pathlib import Path

import pytest

from app.extractors.minsheng import extract_minsheng
from app.validators import validate_statement


SAMPLE_DIR = os.environ.get("MINSHENG_SAMPLE_DIR", "")


@pytest.mark.skipif(not SAMPLE_DIR, reason="未提供民生银行真实样本目录")
def test_real_minsheng_batch_matches_all_statement_totals():
    folder = Path(SAMPLE_DIR)
    pdf_files = sorted(folder.glob("*.pdf"))
    extractions = [extract_minsheng(path) for path in pdf_files]
    reports = [validate_statement(item) for item in extractions if item is not None]

    assert len(pdf_files) == 13
    assert len(extractions) == 13
    assert all(item is not None for item in extractions)
    assert sum(item.page_count for item in extractions if item is not None) == 27
    assert sum(len(item.transactions) for item in extractions if item is not None) == 404
    assert sum(report.status == "零交易通过" for report in reports) == 2
    assert all(report.status in {"通过", "零交易通过"} for report in reports)
    assert all(not report.errors for report in reports)

    march = next(item for item in extractions if item and item.source_path.name == "东方荟界2025.3民生银行流水.pdf")
    first = march.transactions[0]
    assert first.serial_number == "56500202503050007376116"
    assert first.counterparty == "智荟界(成都)商业零售有限公司/128918017410000"
