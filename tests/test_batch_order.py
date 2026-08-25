from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.models import BatchResult, ProcessedStatement, StatementExtraction, Transaction, ValidationReport


def test_approved_transactions_preserve_bank_statement_order_on_same_day():
    source = Path("同日多笔.pdf")
    first = Transaction(
        occurred_at=datetime(2025, 1, 1),
        summary="第一笔",
        voucher_type="转账",
        voucher_number="1",
        debit=Decimal("10.00"),
        credit=Decimal("0.00"),
        balance=Decimal("90.00"),
        serial_number="900",
        counterparty="甲",
        counterparty_bank="",
        bank_name="测试银行",
        account_number="123",
        period_start=None,
        period_end=None,
        source_file=source.name,
        source_page=1,
        extraction_method="测试",
    )
    second = Transaction(
        occurred_at=datetime(2025, 1, 1),
        summary="第二笔",
        voucher_type="转账",
        voucher_number="2",
        debit=Decimal("20.00"),
        credit=Decimal("0.00"),
        balance=Decimal("70.00"),
        serial_number="100",
        counterparty="乙",
        counterparty_bank="",
        bank_name="测试银行",
        account_number="123",
        period_start=None,
        period_end=None,
        source_file=source.name,
        source_page=1,
        extraction_method="测试",
    )
    extraction = StatementExtraction(
        source_path=source,
        bank_name="测试银行",
        account_number="123",
        period_start=None,
        period_end=None,
        page_count=1,
        extraction_method="测试",
        transactions=[first, second],
        declared_count=2,
        declared_debit=Decimal("30.00"),
        declared_credit=Decimal("0.00"),
    )
    batch = BatchResult(
        statements=[
            ProcessedStatement(
                source_path=source,
                extraction=extraction,
                validation=ValidationReport(
                    status="通过",
                    actual_count=2,
                    actual_debit=Decimal("30.00"),
                    actual_credit=Decimal("0.00"),
                ),
            )
        ]
    )

    assert [row.voucher_number for row in batch.approved_transactions] == ["1", "2"]
