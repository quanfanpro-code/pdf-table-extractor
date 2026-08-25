from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.extractors.generic_table import parse_generic_table
from app.extractors.huaxia import is_huaxia_statement, parse_huaxia_pages


def test_huaxia_detector_rejects_other_bank():
    assert is_huaxia_statement("中国民生银行 单位账户对账单") is False


def test_huaxia_parser_keeps_long_identifier_and_source_fields():
    page_text = """华夏银行
对公明细对账单
查询期间总交易笔数：1笔
查询期间借方算数合计金额：0.00
查询期间贷方算数合计金额：100.00
2026-01-02 收款 12345678901234567890 0.00 100.00 100.00 测试摘要 12 345
"""

    extraction = parse_huaxia_pages([page_text], Path("华夏样本.pdf"))
    transaction = extraction.transactions[0]

    assert extraction.declared_count == 1
    assert extraction.declared_debit == Decimal("0.00")
    assert extraction.declared_credit == Decimal("100.00")
    assert transaction.voucher_number == "12345678901234567890"
    assert transaction.serial_number == "12345678901234567890"
    assert transaction.operator == "12"
    assert transaction.transaction_org_code == "345"


def test_generic_table_maps_standard_bank_columns():
    table = [
        [
            "交易时间",
            "摘要",
            "凭证类型",
            "凭证号码",
            "借方发生额",
            "贷方发生额",
            "账户余额",
            "流水号",
            "对方户名/账号",
            "对方行名",
        ],
        [
            "2026/01/02 09:30:00",
            "测试收款",
            "网银凭证",
            "00000001",
            "0.00",
            "100.00",
            "100.00",
            "12345678901234567890",
            "测试公司/123",
            "测试银行",
        ],
    ]

    rows = parse_generic_table(table, Path("普通样本.pdf"), page_number=1)

    assert len(rows) == 1
    assert rows[0].occurred_at == datetime(2026, 1, 2, 9, 30)
    assert rows[0].voucher_number == "00000001"
    assert rows[0].serial_number == "12345678901234567890"
