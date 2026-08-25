from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app.models import StatementExtraction, Transaction


STANDARD_HEADERS = {
    "交易时间": "occurred_at",
    "交易日期": "occurred_at",
    "摘要": "summary",
    "交易摘要": "summary",
    "凭证类型": "voucher_type",
    "凭证种类": "voucher_type",
    "凭证号码": "voucher_number",
    "凭证号": "voucher_number",
    "借方发生额": "debit",
    "借方金额": "debit",
    "贷方发生额": "credit",
    "贷方金额": "credit",
    "账户余额": "balance",
    "余额": "balance",
    "流水号": "serial_number",
    "交易流水号": "serial_number",
    "对方户名/账号": "counterparty",
    "对方户名／账号": "counterparty",
    "对方户名": "counterparty",
    "对方行名": "counterparty_bank",
    "对方开户行": "counterparty_bank",
}

REQUIRED_FIELDS = {
    "occurred_at",
    "summary",
    "voucher_type",
    "voucher_number",
    "debit",
    "credit",
    "balance",
    "serial_number",
    "counterparty",
    "counterparty_bank",
}


def _clean_cell(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _decimal(value: str) -> Decimal:
    cleaned = value.replace(",", "").replace("¥", "").replace("￥", "").strip()
    try:
        return Decimal(cleaned or "0")
    except InvalidOperation as exc:
        raise ValueError(f"金额无法识别：{value!r}") from exc


def _datetime(value: str) -> datetime:
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise ValueError(f"交易时间无法识别：{value!r}")


def _header_mapping(header: list[object]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, value in enumerate(header):
        field_name = STANDARD_HEADERS.get(_clean_cell(value))
        if field_name:
            mapping[field_name] = index
    return mapping


def parse_generic_table(
    table: list[list[object]],
    source_path: Path,
    page_number: int,
) -> list[Transaction]:
    if not table:
        return []

    mapping = _header_mapping(table[0])
    if not REQUIRED_FIELDS.issubset(mapping):
        return []

    rows: list[Transaction] = []
    for raw_row in table[1:]:
        if not raw_row or not any(_clean_cell(value) for value in raw_row):
            continue

        def cell(field_name: str) -> str:
            index = mapping[field_name]
            return _clean_cell(raw_row[index] if index < len(raw_row) else "")

        occurred_at = _datetime(cell("occurred_at"))
        rows.append(
            Transaction(
                occurred_at=occurred_at,
                summary=cell("summary"),
                voucher_type=cell("voucher_type"),
                voucher_number=cell("voucher_number"),
                debit=_decimal(cell("debit")),
                credit=_decimal(cell("credit")),
                balance=_decimal(cell("balance")),
                serial_number=cell("serial_number"),
                counterparty=cell("counterparty"),
                counterparty_bank=cell("counterparty_bank"),
                bank_name="",
                account_number="",
                period_start=occurred_at.date(),
                period_end=occurred_at.date(),
                source_file=source_path.name,
                source_page=page_number,
                extraction_method="普通表格",
            )
        )
    return rows


def extract_generic_table(pdf_path: Path) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    transactions: list[Transaction] = []
    errors: list[str] = []

    with pdfplumber.open(source_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                try:
                    transactions.extend(parse_generic_table(table, source_path, page_number))
                except (IndexError, TypeError, ValueError) as exc:
                    errors.append(
                        f"{source_path.name}：第{page_number}页第{table_number}个表格读取失败：{exc}"
                    )

        if not transactions:
            return None

        period_start = min(item.occurred_at.date() for item in transactions)
        period_end = max(item.occurred_at.date() for item in transactions)
        for item in transactions:
            item.period_start = period_start
            item.period_end = period_end

        return StatementExtraction(
            source_path=source_path,
            bank_name="",
            account_number="",
            period_start=period_start,
            period_end=period_end,
            page_count=len(pdf.pages),
            extraction_method="普通表格",
            transactions=transactions,
            declared_count=None,
            declared_debit=None,
            declared_credit=None,
            errors=errors,
        )
