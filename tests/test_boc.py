import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.extractors.registry import iter_local_extractors
from app.services import process_batch, scan_pdf_files
from app.validators import validate_statement


PAGE_TEXT = """账号 123986813404 账户名称 东方新辰(成都)文化发展有限公司 开户行 中国银行成都东区音乐公园支行 起始日期20250101第 1 页/共 1 页
币种 人民币(CNY) 账户类型 单位人民币活期基本账户存款 承前页余额 100.00 截止日期 20250131 出账周期 月
借方合计 10.00 贷方合计 25.00 本页余额 115.00 本对账期末余额 115.00
"""
PAGE_LAYOUT = """
| 1 |250101|250101|网上支付| |业务编号/用途 | 10.00| | 90.00|14927/9880105/111|张三/中国银行 |
|   |      |      |        |   |补充摘要       |      |       |      |                    |总行          |
| 2 |250102|250102|转账收入| |收款          |      | 25.00|115.00|14927/9880105/222|李四          |
"""


def test_registry_automatically_discovers_boc_extractor():
    assert "中国银行" in [label for label, _extractor in iter_local_extractors()]


def test_boc_parser_merges_wrapped_cells_and_reconciles_amounts():
    from app.extractors.boc import parse_boc_pages

    extraction = parse_boc_pages(
        source_path=Path("中国银行样本.pdf"),
        page_texts=[PAGE_TEXT],
        page_layouts=[PAGE_LAYOUT],
    )

    assert extraction.bank_name == "中国银行"
    assert extraction.account_number == "123986813404"
    assert extraction.period_start == date(2025, 1, 1)
    assert extraction.period_end == date(2025, 1, 31)
    assert extraction.declared_count == 2
    assert extraction.declared_debit == Decimal("10.00")
    assert extraction.declared_credit == Decimal("25.00")
    assert len(extraction.transactions) == 2
    first = extraction.transactions[0]
    assert first.summary == "业务编号/用途补充摘要"
    assert first.counterparty == "张三/中国银行总行"
    assert first.transaction_org_code == "14927"
    assert first.operator == "9880105"
    assert first.serial_number == "111"
    assert validate_statement(extraction).status == "通过"


SAMPLE_DIR = os.environ.get("BOC_SAMPLE_DIR", "")


@pytest.mark.skipif(not SAMPLE_DIR, reason="未提供中国银行真实样本目录")
def test_real_boc_batch_reconciles_all_transaction_statements():
    folder = Path(SAMPLE_DIR)
    pdf_files = [
        path
        for path in scan_pdf_files(folder)
        if path.name != "银行对账单202602.pdf"
    ]
    batch = process_batch(pdf_files, settings=None, force_ai=False)

    assert len(pdf_files) == 22
    assert len(batch.statements) == 22
    assert all(item.extraction is not None for item in batch.statements)
    assert all(item.validation.status == "通过" for item in batch.statements)
    assert all(not item.validation.errors for item in batch.statements)
    assert sum(item.extraction.page_count for item in batch.statements if item.extraction) == 29
    assert len(batch.approved_transactions) == 385
