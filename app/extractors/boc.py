import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from app.models import StatementExtraction, Transaction


EXTRACTOR_LABEL = "中国银行"
BANK_NAME = "中国银行"
AMOUNT = r"-?[\d,]+\.\d{2}"


def _amount(value: str) -> Decimal:
    text = value.strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"无法识别金额：{value}") from exc


def _required(pattern: str, text: str, field_name: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise ValueError(f"未识别到{field_name}")
    return match.group(1)


def _split_reference(reference: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in reference.split("/")]
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[2:])
    return "", "", reference.strip()


def _parse_layout_rows(layout: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in layout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = stripped.split("|")[1:-1]
        if len(cells) != 11:
            continue
        cells = [cell.strip() for cell in cells]
        if cells[0].isdigit() and re.fullmatch(r"\d{6}", cells[1]):
            current = {
                "sequence": int(cells[0]),
                "date": datetime.strptime(cells[1], "%y%m%d"),
                "transaction_type": cells[3],
                "details": cells[5],
                "debit": _amount(cells[6]),
                "credit": _amount(cells[7]),
                "balance": _amount(cells[8]),
                "reference": cells[9],
                "notes": cells[10],
            }
            rows.append(current)
        elif current is not None and not any(cells[:5]):
            current["details"] = str(current["details"]) + cells[5]
            current["reference"] = str(current["reference"]) + cells[9]
            current["notes"] = str(current["notes"]) + cells[10]
    return rows


def is_boc_transaction_statement(page_texts: list[str]) -> bool:
    text = "\n".join(page_texts)
    return all(
        marker in text
        for marker in ("Account No.", "中国银行", "借方合计", "本对账期末余额")
    )


def parse_boc_pages(
    source_path: Path,
    page_texts: list[str],
    page_layouts: list[str],
) -> StatementExtraction:
    if len(page_texts) != len(page_layouts):
        raise ValueError("中国银行页面文本与版式页数不一致")
    if not page_texts:
        raise ValueError("中国银行PDF没有页面")

    first_page = page_texts[0]
    account_number = _required(r"账号\s+(\d+)", first_page, "账号")
    period_start = datetime.strptime(
        _required(r"起始日期\s*(\d{8})", first_page, "起始日期"), "%Y%m%d"
    ).date()
    period_end = datetime.strptime(
        _required(r"截止日期\s*(\d{8})", first_page, "截止日期"), "%Y%m%d"
    ).date()

    errors: list[str] = []
    parsed_rows: list[dict[str, object]] = []
    declared_debit = Decimal("0")
    declared_credit = Decimal("0")
    for page_number, (page_text, page_layout) in enumerate(
        zip(page_texts, page_layouts), start=1
    ):
        previous_balance = _amount(
            _required(rf"承前页余额\s+({AMOUNT})", page_text, f"第{page_number}页承前页余额")
        )
        totals = re.search(
            rf"借方合计\s+({AMOUNT})\s+贷方合计\s+({AMOUNT})"
            rf"\s+本页余额\s+({AMOUNT})\s+本对账期末余额\s+({AMOUNT})",
            page_text,
        )
        if totals is None:
            raise ValueError(f"未识别到第{page_number}页合计")
        page_debit = _amount(totals.group(1))
        page_credit = _amount(totals.group(2))
        page_balance = _amount(totals.group(3))
        period_balance = _amount(totals.group(4))
        page_rows = _parse_layout_rows(page_layout)

        sequences = [int(row["sequence"]) for row in page_rows]
        if sequences != list(range(1, len(page_rows) + 1)):
            errors.append(f"{source_path.name}：第{page_number}页序号不连续")
        actual_debit = sum((row["debit"] for row in page_rows), Decimal("0"))
        actual_credit = sum((row["credit"] for row in page_rows), Decimal("0"))
        if actual_debit != page_debit:
            errors.append(
                f"{source_path.name}：第{page_number}页借方合计不符，"
                f"声明值={page_debit:.2f}，实际值={actual_debit:.2f}"
            )
        if actual_credit != page_credit:
            errors.append(
                f"{source_path.name}：第{page_number}页贷方合计不符，"
                f"声明值={page_credit:.2f}，实际值={actual_credit:.2f}"
            )

        running_balance = previous_balance
        for row in page_rows:
            running_balance = running_balance - row["debit"] + row["credit"]
            if running_balance != row["balance"]:
                errors.append(
                    f"{source_path.name}：第{page_number}页第{row['sequence']}笔余额不符"
                )
            row["source_page"] = page_number
            parsed_rows.append(row)
        if running_balance != page_balance:
            errors.append(f"{source_path.name}：第{page_number}页页末余额不符")
        if page_number == len(page_texts) and page_balance != period_balance:
            errors.append(f"{source_path.name}：末页余额与对账期末余额不符")
        declared_debit += page_debit
        declared_credit += page_credit

    if not parsed_rows:
        raise ValueError("未识别到中国银行交易明细")

    extraction_method = "中国银行固定版式"
    transactions = []
    for row in parsed_rows:
        org_code, operator, serial_number = _split_reference(str(row["reference"]))
        transactions.append(
            Transaction(
                occurred_at=row["date"],
                summary=str(row["details"]) or str(row["transaction_type"]),
                voucher_type=str(row["transaction_type"]),
                voucher_number=str(row["sequence"]),
                debit=row["debit"],
                credit=row["credit"],
                balance=row["balance"],
                serial_number=serial_number,
                counterparty=str(row["notes"]),
                counterparty_bank="",
                bank_name=BANK_NAME,
                account_number=account_number,
                period_start=period_start,
                period_end=period_end,
                source_file=source_path.name,
                source_page=int(row["source_page"]),
                extraction_method=extraction_method,
                operator=operator,
                transaction_org_code=org_code,
            )
        )

    return StatementExtraction(
        source_path=source_path,
        bank_name=BANK_NAME,
        account_number=account_number,
        period_start=period_start,
        period_end=period_end,
        page_count=len(page_texts),
        extraction_method=extraction_method,
        transactions=transactions,
        declared_count=len(parsed_rows),
        declared_debit=declared_debit,
        declared_credit=declared_credit,
        errors=errors,
    )


def extract_boc(pdf_path: Path) -> StatementExtraction | None:
    source_path = Path(pdf_path)
    with pdfplumber.open(source_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]
        if not is_boc_transaction_statement(page_texts):
            return None
        page_layouts = [
            page.extract_text(layout=True, x_density=7.25, y_density=13) or ""
            for page in pdf.pages
        ]
    return parse_boc_pages(source_path, page_texts, page_layouts)
