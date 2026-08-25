import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app.models import StatementExtraction, Transaction


BANK_NAME = "成都农村商业银行股份有限公司"
EXPECTED_HEADERS = [
    "序号",
    "子序号",
    "交易日期",
    "摘要",
    "币种",
    "借方金额",
    "贷方金额",
    "账户余额",
    "对方账号",
    "对方户名",
]


def _clean(value: object) -> str:
    return "".join(str(value or "").split())


def _decimal(value: object) -> Decimal:
    text = _clean(value).replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"无法识别金额：{value}") from exc


def _required_match(pattern: str, text: str, field_name: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"未识别到{field_name}")
    return match.group(1)


def is_chengdu_rural_statement(page_texts: list[str]) -> bool:
    text = _clean("\n".join(page_texts))
    return all(
        marker in text
        for marker in ("银行电子对账单", "借款方总额", "贷款方总额", "子序号")
    )


def parse_chengdu_rural_pages(
    source_path: Path,
    page_texts: list[str],
    page_tables: list[list[list[list[str | None]]]],
) -> StatementExtraction:
    header_text = _clean("\n".join(page_texts))
    account_number = _required_match(r"账号[：:](\d+)", header_text, "账号")
    statement_month = _required_match(
        r"月份[：:](\d{4}年\d{2}月)", header_text, "月份"
    )
    declared_debit = _decimal(
        _required_match(r"借款方总额[：:]([0-9,.]+)", header_text, "借款方总额")
    )
    declared_credit = _decimal(
        _required_match(r"贷款方总额[：:]([0-9,.]+)", header_text, "贷款方总额")
    )

    parsed_rows: list[dict[str, object]] = []
    currencies: set[str] = set()
    for page_number, tables in enumerate(page_tables, start=1):
        for table in tables or []:
            if not table or [_clean(cell) for cell in table[0][:10]] != EXPECTED_HEADERS:
                continue
            for row in table[1:]:
                if not row or len(row) < 10 or not _clean(row[0]):
                    continue
                sequence_text = _clean(row[0])
                try:
                    sequence = int(sequence_text)
                except ValueError as exc:
                    raise ValueError(f"无法识别序号：{row[0]}") from exc
                occurred_at = datetime.strptime(_clean(row[2]), "%Y%m%d")
                currency = _clean(row[4])
                if currency:
                    currencies.add(currency)
                counterparty_account = _clean(row[8])
                counterparty_name = _clean(row[9])
                counterparty = "/".join(
                    value for value in (counterparty_name, counterparty_account) if value
                )
                parsed_rows.append(
                    {
                        "sequence": sequence,
                        "sequence_text": sequence_text,
                        "occurred_at": occurred_at,
                        "summary": _clean(row[3]),
                        "debit": _decimal(row[5]),
                        "credit": _decimal(row[6]),
                        "balance": _decimal(row[7]),
                        "serial_number": _clean(row[1]),
                        "counterparty": counterparty,
                        "source_page": page_number,
                    }
                )

    if not parsed_rows:
        raise ValueError("未识别到成都农商行交易明细")

    parsed_rows.sort(key=lambda item: (item["occurred_at"], -int(item["sequence"])))
    period_start = parsed_rows[0]["occurred_at"].date()
    period_end = parsed_rows[-1]["occurred_at"].date()
    declared_count = max(int(item["sequence"]) for item in parsed_rows)
    errors: list[str] = []
    actual_sequences = sorted(int(item["sequence"]) for item in parsed_rows)
    if actual_sequences != list(range(1, declared_count + 1)):
        errors.append(f"{source_path.name}：序号不连续或存在重复")

    currency_text = "、".join(sorted(currencies)) or "未识别"
    extraction_method = (
        f"成都农商行固定表格（原表月份：{statement_month}；币种：{currency_text}）"
    )
    transactions = [
        Transaction(
            occurred_at=item["occurred_at"],
            summary=str(item["summary"]),
            voucher_type="",
            voucher_number=str(item["sequence_text"]),
            debit=item["debit"],
            credit=item["credit"],
            balance=item["balance"],
            serial_number=str(item["serial_number"]),
            counterparty=str(item["counterparty"]),
            counterparty_bank="",
            bank_name=BANK_NAME,
            account_number=account_number,
            period_start=period_start,
            period_end=period_end,
            source_file=source_path.name,
            source_page=int(item["source_page"]),
            extraction_method=extraction_method,
        )
        for item in parsed_rows
    ]

    return StatementExtraction(
        source_path=source_path,
        bank_name=BANK_NAME,
        account_number=account_number,
        period_start=period_start,
        period_end=period_end,
        page_count=len(page_texts),
        extraction_method=extraction_method,
        transactions=transactions,
        declared_count=declared_count,
        declared_debit=declared_debit,
        declared_credit=declared_credit,
        errors=errors,
    )


def extract_chengdu_rural(pdf_path: Path) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    with pdfplumber.open(source_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        if not is_chengdu_rural_statement(page_texts):
            return None
        page_tables = [page.extract_tables() or [] for page in pdf.pages]
    return parse_chengdu_rural_pages(source_path, page_texts, page_tables)
