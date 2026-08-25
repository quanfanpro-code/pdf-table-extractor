import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app.models import StatementExtraction, Transaction


EXTRACTOR_LABEL = "华夏银行"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")
AMOUNT_PATTERN = re.compile(r"^[0-9,]+\.\d{2}$")
INTEGER_PATTERN = re.compile(r"^\d+$")
FOOTER_PREFIXES = (
    "本页借方算数合计金额",
    "本页贷方算数合计金额",
    "查询期间借方算数合计金额",
    "查询期间贷方算数合计金额",
    "查询期间总交易笔数",
    "银行提请注意",
    "查询时间",
    "记账日期",
)


def is_huaxia_statement(text: str) -> bool:
    return "华夏银行" in (text or "") and "对公明细对账单" in (text or "")


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"金额无法识别：{value!r}") from exc


def _compact_chinese(tokens: list[str]) -> str:
    value = " ".join(tokens).strip()
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", value)


def _declared_values(full_text: str) -> tuple[int | None, Decimal | None, Decimal | None]:
    count_match = re.search(r"查询期间总交易笔数[：:]\s*(\d+)\s*笔", full_text)
    debit_match = re.search(r"查询期间借方算数合计金额[：:]\s*([0-9,.]+)", full_text)
    credit_match = re.search(r"查询期间贷方算数合计金额[：:]\s*([0-9,.]+)", full_text)
    return (
        int(count_match.group(1)) if count_match else None,
        _decimal(debit_match.group(1)) if debit_match else None,
        _decimal(credit_match.group(1)) if credit_match else None,
    )


def _parse_record(
    date_line: str,
    previous_lines: list[str],
    next_lines: list[str],
    source_path: Path,
    page_number: int,
) -> Transaction | None:
    date_match = DATE_PATTERN.match(date_line)
    if not date_match:
        return None

    tokens = date_line[date_match.end() :].strip().split()
    if len(tokens) < 7 or not (
        INTEGER_PATTERN.fullmatch(tokens[-2]) and INTEGER_PATTERN.fullmatch(tokens[-1])
    ):
        return None

    operator, org_code = tokens[-2:]
    core = tokens[:-2]
    amount_positions = [index for index, token in enumerate(core) if AMOUNT_PATTERN.fullmatch(token)]
    if len(amount_positions) < 3:
        return None

    debit_index, credit_index, balance_index = amount_positions[-3:]
    before_amounts = core[:debit_index]
    after_balance = core[balance_index + 1 :]

    voucher_index = next(
        (index for index, token in enumerate(before_amounts) if re.fullmatch(r"[A-Za-z0-9]{7,}", token)),
        None,
    )
    voucher_number = before_amounts[voucher_index] if voucher_index is not None else ""
    voucher_type_parts = before_amounts[:voucher_index] if voucher_index is not None else before_amounts
    summary_parts = [line for line in previous_lines if len(line) > 3]
    summary_parts.extend(after_balance)
    if not after_balance:
        summary_parts.extend(line for line in next_lines if len(line) <= 5)

    occurred_at = datetime.strptime(date_match.group(), "%Y-%m-%d")
    return Transaction(
        occurred_at=occurred_at,
        summary=_compact_chinese(summary_parts),
        voucher_type=_compact_chinese(voucher_type_parts),
        voucher_number=voucher_number,
        debit=_decimal(core[debit_index]),
        credit=_decimal(core[credit_index]),
        balance=_decimal(core[balance_index]),
        serial_number=voucher_number,
        counterparty="",
        counterparty_bank="",
        bank_name="华夏银行",
        account_number="",
        period_start=None,
        period_end=None,
        source_file=source_path.name,
        source_page=page_number,
        extraction_method="华夏银行文本",
        operator=operator,
        transaction_org_code=org_code,
    )


def parse_huaxia_pages(page_texts: list[str], source_path: Path) -> StatementExtraction:
    full_text = "\n".join(page_texts)
    declared_count, declared_debit, declared_credit = _declared_values(full_text)
    transactions: list[Transaction] = []
    errors: list[str] = []

    for page_number, text in enumerate(page_texts, start=1):
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        lines = [line for line in lines if not line.startswith(FOOTER_PREFIXES)]
        date_indices = [index for index, line in enumerate(lines) if DATE_PATTERN.match(line)]

        for record_number, date_index in enumerate(date_indices):
            previous_start = date_indices[record_number - 1] + 1 if record_number else 0
            next_end = date_indices[record_number + 1] if record_number + 1 < len(date_indices) else len(lines)
            try:
                transaction = _parse_record(
                    lines[date_index],
                    lines[previous_start:date_index],
                    lines[date_index + 1 : next_end],
                    source_path,
                    page_number,
                )
                if transaction:
                    transactions.append(transaction)
            except (IndexError, TypeError, ValueError) as exc:
                errors.append(f"{source_path.name}：第{page_number}页第{record_number + 1}条读取失败：{exc}")

    period_start = min((item.occurred_at.date() for item in transactions), default=None)
    period_end = max((item.occurred_at.date() for item in transactions), default=None)
    for item in transactions:
        item.period_start = period_start
        item.period_end = period_end

    return StatementExtraction(
        source_path=source_path,
        bank_name="华夏银行",
        account_number="",
        period_start=period_start,
        period_end=period_end,
        page_count=len(page_texts),
        extraction_method="华夏银行文本",
        transactions=transactions,
        declared_count=declared_count,
        declared_debit=declared_debit,
        declared_credit=declared_credit,
        errors=errors,
    )


def extract_huaxia(pdf_path: Path) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    with pdfplumber.open(source_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
    if not page_texts or not is_huaxia_statement(page_texts[0]):
        return None
    return parse_huaxia_pages(page_texts, source_path)
