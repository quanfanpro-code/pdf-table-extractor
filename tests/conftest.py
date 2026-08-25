from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import StatementExtraction, Transaction


def make_transaction(
    occurred_at: datetime,
    debit: str,
    credit: str,
    balance: str,
    serial_number: str,
) -> Transaction:
    return Transaction(
        occurred_at=occurred_at,
        summary="测试交易",
        voucher_type="网银凭证",
        voucher_number="00000001",
        debit=Decimal(debit),
        credit=Decimal(credit),
        balance=Decimal(balance),
        serial_number=serial_number,
        counterparty="测试单位/123456",
        counterparty_bank="测试银行",
        bank_name="测试银行",
        account_number="650103833",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        source_file="测试.pdf",
        source_page=1,
        extraction_method="测试",
    )


@pytest.fixture
def sample_extraction() -> StatementExtraction:
    transactions = [
        make_transaction(datetime(2026, 1, 1, 9, 0), "0.00", "100.00", "100.00", "10001"),
        make_transaction(datetime(2026, 1, 2, 10, 0), "25.00", "0.00", "75.00", "10002"),
    ]
    return StatementExtraction(
        source_path=Path("测试.pdf"),
        bank_name="测试银行",
        account_number="650103833",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        page_count=1,
        extraction_method="测试",
        transactions=transactions,
        declared_count=2,
        declared_debit=Decimal("25.00"),
        declared_credit=Decimal("100.00"),
    )


@pytest.fixture
def zero_extraction() -> StatementExtraction:
    return StatementExtraction(
        source_path=Path("零交易.pdf"),
        bank_name="测试银行",
        account_number="650103833",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        page_count=1,
        extraction_method="测试",
        transactions=[],
        declared_count=0,
        declared_debit=Decimal("0.00"),
        declared_credit=Decimal("0.00"),
    )
