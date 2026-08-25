from datetime import date
from decimal import Decimal
from pathlib import Path

from app.extractors.chengdu_rural import parse_chengdu_rural_pages
from app.validators import validate_statement


PAGE_TEXT = """银行电子对账单
账 号：1000030011702619 月份：2025年06月
户 名：东方农博（成都）商业运营管理有限公司
开户银行：新津兴义支行 借款方总额：35400 贷款方总额：7925.63
序号 子序号 交易日期 摘要 币种 借方金额 贷方金额 账户余额 对方账号 对方户名
"""

PAGE_TABLE = [
    ["序号", "子序号", "交易日期", "摘要", "币种", "借方金额", "贷方金额", "账户余额", "对方账号", "对方户名"],
    ["1", "000156", "20250627", "存现", "人民币", "", "170", "532.99", "", ""],
    ["2", "000156", "20250621", "入息", "人民币", "", "5.63", "362.99", "", ""],
    ["3", "000156", "20250605", "存现", "人民币", "", "260", "357.36", "", ""],
    ["4", "000156", "20250528", "跨行转账", "人民币", "35400", "", "97.36", "648462385", "东方农博（成都）商业\n运营管理有限公司"],
    ["5", "000156", "20250528", "存现", "人民币", "", "2800", "35497.36", "", ""],
    ["6", "000156", "20250516", "存现", "人民币", "", "2540", "32697.36", "", ""],
    ["7", "000156", "20250402", "存现", "人民币", "", "2150", "30157.36", "", ""],
]


def _parse():
    return parse_chengdu_rural_pages(
        source_path=Path("东方农博2025.6成都农商行流水.pdf"),
        page_texts=[PAGE_TEXT],
        page_tables=[[PAGE_TABLE]],
    )


def test_parse_chengdu_rural_header_and_totals():
    extraction = _parse()

    assert extraction.bank_name == "成都农村商业银行股份有限公司"
    assert extraction.account_number == "1000030011702619"
    assert extraction.period_start == date(2025, 4, 2)
    assert extraction.period_end == date(2025, 6, 27)
    assert extraction.declared_count == 7
    assert extraction.declared_debit == Decimal("35400")
    assert extraction.declared_credit == Decimal("7925.63")
    assert "原表月份：2025年06月" in extraction.extraction_method
    assert "币种：人民币" in extraction.extraction_method


def test_parse_chengdu_rural_restores_balance_order_and_validates():
    extraction = _parse()
    transactions = extraction.transactions

    assert len(transactions) == 7
    may_28 = [row for row in transactions if row.occurred_at.date() == date(2025, 5, 28)]
    assert [row.voucher_number for row in may_28] == ["5", "4"]
    assert [row.balance for row in may_28] == [Decimal("35497.36"), Decimal("97.36")]
    assert may_28[1].counterparty == "东方农博（成都）商业运营管理有限公司/648462385"
    assert may_28[1].serial_number == "000156"
    assert may_28[1].summary == "跨行转账"
    assert validate_statement(extraction).status == "通过"
