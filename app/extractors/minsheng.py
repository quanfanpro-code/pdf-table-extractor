import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app.models import StatementExtraction, Transaction


COLUMN_BOUNDS = (0, 61, 200, 234, 311, 385, 459, 498, 546, 711, 843)
DATE_PATTERN = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def _compact(text: str) -> str:
    return re.sub(r"[_\s]", "", text or "").replace("：", ":")


def _decimal(text: str) -> Decimal:
    value = (text or "").replace(",", "").replace(" ", "").strip()
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"金额无法识别：{text!r}") from exc


def parse_footer(text: str) -> tuple[int | None, Decimal | None, Decimal | None]:
    compact = _compact(text)
    count_match = re.search(r"合计笔数:(\d+)", compact)
    debit_match = re.search(r"借方发生总额:([0-9,.]+)", compact)
    credit_match = re.search(r"贷方发生总额:([0-9,.]+)", compact)
    return (
        int(count_match.group(1)) if count_match else None,
        _decimal(debit_match.group(1)) if debit_match else None,
        _decimal(credit_match.group(1)) if credit_match else None,
    )


def _column_index(x0: float) -> int | None:
    for index in range(len(COLUMN_BOUNDS) - 1):
        if COLUMN_BOUNDS[index] <= x0 < COLUMN_BOUNDS[index + 1]:
            return index
    return None


def _footer_top(words: list[dict], page_height: float) -> float:
    candidates = []
    for item in words:
        compact = _compact(str(item.get("text", "")))
        if "借方发生总额" in compact or compact.startswith("打印渠道"):
            candidates.append(float(item["top"]))
    return min(candidates) if candidates else page_height - 35


def parse_page_words(
    words: list[dict],
    page_number: int,
    source_file: str,
    account_number: str,
    period_start: date | None,
    period_end: date | None,
    page_height: float,
) -> list[Transaction]:
    date_words = sorted(
        (
            item
            for item in words
            if float(item.get("x0", 999)) < COLUMN_BOUNDS[1]
            and float(item.get("top", 0)) > 100
            and DATE_PATTERN.fullmatch(str(item.get("text", "")))
        ),
        key=lambda item: float(item["top"]),
    )
    footer_top = _footer_top(words, page_height)
    transactions: list[Transaction] = []

    for index, date_word in enumerate(date_words):
        start_top = float(date_word["top"]) - 0.5
        next_top = (
            float(date_words[index + 1]["top"]) - 0.5
            if index + 1 < len(date_words)
            else footer_top
        )
        cells: list[list[dict]] = [[] for _ in range(10)]

        for item in words:
            top = float(item.get("top", 0))
            if not start_top <= top < next_top:
                continue
            column = _column_index(float(item.get("x0", -1)))
            if column is not None:
                cells[column].append(item)

        values: list[str] = []
        for column, items in enumerate(cells):
            items.sort(key=lambda item: (round(float(item["top"]), 1), float(item["x0"])))
            separator = " " if column == 0 else ""
            values.append(separator.join(str(item["text"]).strip() for item in items).strip())

        occurred_at = datetime.strptime(values[0], "%Y/%m/%d %H:%M:%S")
        transactions.append(
            Transaction(
                occurred_at=occurred_at,
                summary=values[1],
                voucher_type=values[2],
                voucher_number=values[3],
                debit=_decimal(values[4]),
                credit=_decimal(values[5]),
                balance=_decimal(values[6]),
                serial_number=values[7],
                counterparty=values[8],
                counterparty_bank=values[9],
                bank_name="中国民生银行",
                account_number=account_number,
                period_start=period_start,
                period_end=period_end,
                source_file=source_file,
                source_page=page_number,
                extraction_method="民生银行固定栏目",
            )
        )

    return transactions


def extract_minsheng(pdf_path: Path) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    with pdfplumber.open(source_path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        if "中国民生银行" not in first_text or "单位账户对账单" not in first_text:
            return None

        page_texts = [page.extract_text() or "" for page in pdf.pages]
        full_text = "\n".join(page_texts)
        account_match = re.search(r"客户账号[:：]\s*(\d+)", full_text)
        period_match = re.search(
            r"起止日期[:：]\s*(\d{4}/\d{2}/\d{2})\s*-\s*(\d{4}/\d{2}/\d{2})",
            full_text,
        )
        account_number = account_match.group(1) if account_match else ""
        period_start = datetime.strptime(period_match.group(1), "%Y/%m/%d").date() if period_match else None
        period_end = datetime.strptime(period_match.group(2), "%Y/%m/%d").date() if period_match else None
        declared_count, declared_debit, declared_credit = parse_footer(full_text)
        transactions: list[Transaction] = []
        errors: list[str] = []

        if not account_number:
            errors.append(f"{source_path.name}：未识别客户账号")
        if not period_match:
            errors.append(f"{source_path.name}：未识别对账期间")

        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                transactions.extend(
                    parse_page_words(
                        page.extract_words(
                            x_tolerance=1,
                            y_tolerance=2,
                            keep_blank_chars=False,
                            use_text_flow=False,
                        ),
                        page_number=page_number,
                        source_file=source_path.name,
                        account_number=account_number,
                        period_start=period_start,
                        period_end=period_end,
                        page_height=float(page.height),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{source_path.name}：第{page_number}页读取失败：{exc}")

        return StatementExtraction(
            source_path=source_path,
            bank_name="中国民生银行",
            account_number=account_number,
            period_start=period_start,
            period_end=period_end,
            page_count=len(pdf.pages),
            extraction_method="民生银行固定栏目",
            transactions=transactions,
            declared_count=declared_count,
            declared_debit=declared_debit,
            declared_credit=declared_credit,
            errors=errors,
        )
