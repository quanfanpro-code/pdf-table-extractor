from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


@dataclass(slots=True)
class Transaction:
    occurred_at: datetime
    summary: str
    voucher_type: str
    voucher_number: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    serial_number: str
    counterparty: str
    counterparty_bank: str
    bank_name: str
    account_number: str
    period_start: date | None
    period_end: date | None
    source_file: str
    source_page: int
    extraction_method: str
    operator: str = ""
    transaction_org_code: str = ""


@dataclass(slots=True)
class StatementExtraction:
    source_path: Path
    bank_name: str
    account_number: str
    period_start: date | None
    period_end: date | None
    page_count: int
    extraction_method: str
    transactions: list[Transaction]
    declared_count: int | None
    declared_debit: Decimal | None
    declared_credit: Decimal | None
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationReport:
    status: str
    actual_count: int
    actual_debit: Decimal
    actual_credit: Decimal
    balance_break_rows: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessedStatement:
    source_path: Path
    extraction: StatementExtraction | None
    validation: ValidationReport


@dataclass(slots=True)
class BatchResult:
    statements: list[ProcessedStatement]

    @property
    def approved_transactions(self) -> list[Transaction]:
        rows = [
            transaction
            for statement in self.statements
            if statement.validation.status in {"通过", "零交易通过"}
            and statement.extraction is not None
            for transaction in statement.extraction.transactions
        ]
        return sorted(
            rows,
            key=lambda item: (
                item.occurred_at,
                item.source_file.casefold(),
                item.source_page,
                item.serial_number,
            ),
        )
