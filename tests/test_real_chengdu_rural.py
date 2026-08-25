import os
from datetime import date
from pathlib import Path

import pytest

from app.services import process_batch, scan_pdf_files


SAMPLE_DIR = os.environ.get("CHENGDU_RURAL_SAMPLE_DIR", "")


@pytest.mark.skipif(not SAMPLE_DIR, reason="未提供成都农商行真实样本目录")
def test_real_chengdu_rural_batch_all_passes():
    folder = Path(SAMPLE_DIR)
    pdf_files = scan_pdf_files(folder)
    batch = process_batch(pdf_files, settings=None, force_ai=False)

    assert len(pdf_files) == 3
    assert len(batch.statements) == 3
    assert all(item.extraction is not None for item in batch.statements)
    assert all(item.validation.status == "通过" for item in batch.statements)
    assert all(not item.validation.errors for item in batch.statements)
    assert sum(item.extraction.page_count for item in batch.statements if item.extraction) == 3
    assert len(batch.approved_transactions) == 17
    assert batch.approved_transactions[0].occurred_at.date() == date(2025, 3, 11)
    assert batch.approved_transactions[-1].occurred_at.date() == date(2025, 9, 22)
