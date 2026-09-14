"""Read electronic statement tables using header labels and character gutters.

No bank identity or fixed page coordinates select this parser. Unknown layouts
fail closed: row coverage is evidence only after every page has been accounted for.
"""
import re
from bisect import bisect_right
from decimal import Decimal
from pathlib import Path

import pdfplumber

from app.extractors.generic_table import STANDARD_HEADERS, _datetime
from app.models import StatementExtraction, Transaction
from app.progress import report_progress
from app.对账单控制信息 import AMOUNT, enrich_from_pages

EXTRACTOR_LABEL = "通用文字对齐"
HEADERS = {
    **STANDARD_HEADERS,
    "日期": "occurred_at", "业务类型": "voucher_type", "票据号": "voucher_number",
    "对手户名": "counterparty", "对手名称": "counterparty", "对方名称": "counterparty",
    "借方/贷方金额": "signed_amount", "借方／贷方金额": "signed_amount",
    "借方贷方金额": "signed_amount", "借/贷金额": "signed_amount",
    "支出金额": "debit", "收入金额": "credit", "支出": "debit", "收入": "credit",
    "借方": "debit", "贷方": "credit", "交易后余额": "balance",
}
MONEY_FIELDS = {"debit", "credit", "signed_amount", "balance"}
CONTINUATION_FIELDS = {"summary", "counterparty", "counterparty_bank"}
FOOTER = re.compile(r"第\s*\d+\s*页|期末余额|本页合计|本期.*合计|借方合计|贷方合计|交易笔数|总笔数|特别提示|打印时间")


def _lines(chars):
    lines = []
    for char in sorted((c for c in chars if c["text"].strip()), key=lambda c: (c["top"], c["x0"])):
        if not lines or abs(char["top"] - lines[-1][0]["top"]) > 2:
            lines.append([])
        lines[-1].append(char)
    return [sorted(line, key=lambda c: c["x0"]) for line in lines]


def _text(chars, compact=False):
    result = ""
    previous = None
    for char in chars:
        if not compact and previous and char["x0"] - previous["x1"] > max(.5, char["size"] * .2):
            result += " "
        result += char["text"]
        previous = char
    return result.strip()


def _header(line):
    text = _text(line, compact=True)
    taken = set()
    columns = []
    for label, field in sorted(HEADERS.items(), key=lambda pair: -len(pair[0])):
        for match in re.finditer(re.escape(label), text):
            positions = set(range(match.start(), match.end()))
            if positions & taken:
                continue
            taken.update(positions)
            columns.append((field, line[match.start()]["x0"], line[match.end() - 1]["x1"]))
    fields = [col[0] for col in columns]
    if ("occurred_at" not in fields or "balance" not in fields
            or not ("signed_amount" in fields or {"debit", "credit"} <= set(fields))):
        return None
    if len(fields) != len(set(fields)):
        return None
    return sorted(columns, key=lambda col: col[1])


def _cuts(columns, body):
    """Find empty vertical gutters between header labels in the actual body.

    This handles right-aligned amounts and labels touching adjacent text without
    assuming that the left edge of a numeric label is the left edge of its data.
    """
    cuts = []
    for left, right in zip(columns, columns[1:]):
        lo, hi = left[2], right[1]
        if hi <= lo:
            raise ValueError("表头列重叠")
        occupied = sorted((max(lo, c["x0"]), min(hi, c["x1"]))
                          for line in body for c in line if c["x1"] > lo and c["x0"] < hi)
        gaps, end = [], lo
        for start, stop in occupied:
            if start > end:
                gaps.append((end, start))
            end = max(end, stop)
        if end < hi:
            gaps.append((end, hi))
        gaps = [gap for gap in gaps if gap[1] - gap[0] >= .5]
        if not gaps:
            if left[0] in MONEY_FIELDS:
                cuts.append((lo + hi) / 2)
                continue
            raise ValueError(f"无法可靠分隔{left[0]}与{right[0]}列")
        start, stop = max(gaps, key=lambda gap: gap[1] - gap[0])
        cuts.append((start + stop) / 2)
    return cuts


def _cells(line, columns, cuts):
    cuts = list(cuts)
    for i, (left, right) in enumerate(zip(columns, columns[1:])):
        if left[0] in MONEY_FIELDS:
            start = cuts[i - 1] if i else -float("inf")
            tail = [c for c in line if (c["x0"] + c["x1"]) / 2 > start]
            match = re.match(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}", _text(tail, compact=True))
            if match and tail[0]["x0"] < cuts[i]:
                cuts[i] = tail[match.end() - 1]["x1"] + .1
    parts = [[] for _ in columns]
    for char in line:
        index = bisect_right(cuts, (char["x0"] + char["x1"]) / 2)
        parts[index].append(char)
    return {column[0]: _text(part) for column, part in zip(columns, parts)}


def _amount(value, blank=False):
    cleaned = value.replace(",", "").replace("，", "").replace("￥", "").replace("¥", "").strip()
    if not cleaned and blank:
        return Decimal("0.00")
    if not re.fullmatch(r"[+-]?\d+\.\d{2}", cleaned):
        raise ValueError("金额缺失或格式无法识别")
    return Decimal(cleaned)


def _transaction(cells, path, page):
    date = _datetime(cells.get("occurred_at", ""))
    if "signed_amount" in cells:
        amount = _amount(cells["signed_amount"])
        debit, credit = max(-amount, Decimal(0)), max(amount, Decimal(0))
    else:
        if not cells.get("debit") and not cells.get("credit"):
            raise ValueError("借贷金额均为空")
        debit = _amount(cells.get("debit", ""), blank=True)
        credit = _amount(cells.get("credit", ""), blank=True)
        if debit < 0 or credit < 0:
            raise ValueError("借贷分列出现负数，方向需核实")
    if re.match(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}", cells.get("counterparty", "")):
        raise ValueError("户名区域出现额外金额，疑似金额串行或错位")
    return Transaction(
        occurred_at=date, summary=cells.get("summary", ""),
        voucher_type=cells.get("voucher_type", ""), voucher_number=cells.get("voucher_number", ""),
        debit=debit, credit=credit, balance=_amount(cells.get("balance", "")),
        serial_number=cells.get("serial_number", ""), counterparty=cells.get("counterparty", ""),
        counterparty_bank=cells.get("counterparty_bank", ""), bank_name="", account_number="",
        period_start=None, period_end=None, source_file=path.name, source_page=page,
        extraction_method=EXTRACTOR_LABEL,
    )


def _metadata(extraction, metadata_texts):
    metadata = "\n".join(metadata_texts)
    accounts = set(re.findall(r"(?<!对方)(?<!对手)账号\s*[：:]\s*([\d*＊-]+)", metadata))
    if len(accounts) == 1:
        extraction.account_number = accounts.pop()
    elif len(accounts) > 1:
        extraction.errors.append("不同页账号不一致，无法作为单一账户核对")
    banks = set(re.findall(r"([\u4e00-\u9fff]{2,20}银行)(?:股份有限公司)?", metadata))
    banks -= {"开户银行", "对方银行", "对手银行"}
    if len(banks) == 1:
        extraction.bank_name = banks.pop()
    elif len(banks) > 1:
        extraction.warnings.append("页眉页脚存在多个银行名称，银行名称未确定，期间衔接不强行关联")
    patterns = {
        "declared_count": r"(?:本期交易笔数|交易笔数|总笔数)\s*[：:]?\s*(\d+)",
        "declared_debit": rf"(?:本期|账单)?借方合计\s*[：:]?\s*{AMOUNT}",
        "declared_credit": rf"(?:本期|账单)?贷方合计\s*[：:]?\s*{AMOUNT}",
    }
    for field, pattern in patterns.items():
        values = {int(raw) if field == "declared_count" else Decimal(raw.replace(",", ""))
                  for raw in re.findall(pattern, metadata)}
        if len(values) == 1:
            setattr(extraction, field, values.pop())
        elif len(values) > 1:
            extraction.errors.append(f"原件{field}存在不同数值，需核对合计范围")
    enrich_from_pages(extraction, metadata_texts)


def extract_text_align(pdf_path: Path) -> StatementExtraction | None:
    path = Path(pdf_path)
    transactions, errors = [], []
    seen_header = False
    serial_required = False
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        metadata_texts = [""] * page_count
        for page_no, page in enumerate(pdf.pages, 1):
            report_progress(f"{path.name}：文字对齐，第 {page_no}/{page_count} 页")
            text = page.extract_text() or ""
            lines = _lines(page.dedupe_chars().chars)
            headers = []
            for i, line in enumerate(lines):
                columns = _header(line)
                end = i
                if columns is None and i + 1 < len(lines) and lines[i + 1][0]["top"] - line[0]["top"] <= 4.5:
                    columns = _header(sorted(line + lines[i + 1], key=lambda c: c["x0"]))
                    end = i + 1
                if columns:
                    headers.append((end, columns))
            if len(headers) != 1:
                errors.append(f"第{page_no}页未识别到唯一完整表头，未能确认全部交易行")
                continue
            seen_header = True
            header_index, columns = headers[0]
            metadata_texts[page_no - 1] = "\n".join(_text(line) for line in lines[:header_index])
            serial_required |= any(col[0] == "serial_number" for col in columns)
            body = []
            for body_index, line in enumerate(lines[header_index + 1:], header_index + 1):
                compact = _text(line, compact=True)
                if (FOOTER.match(compact) and line[0]["x0"] <= columns[0][1] + 20):
                    metadata_texts[page_no - 1] += "\n" + "\n".join(_text(item) for item in lines[body_index:])
                    break
                # Bilingual header lines are allowed before the first data row.
                if (not body and re.fullmatch(r"[A-Za-z/().]+", compact)
                        and re.search(r"Date|Business|Credit|Balance|Name|Type|No\.|Amount|Counterparty", compact)):
                    continue
                body.append(line)
            if not body:
                errors.append(f"第{page_no}页没有可核对交易，不能仅凭空表判为零交易")
                continue
            try:
                cuts = _cuts(columns, body)
            except ValueError as exc:
                errors.append(f"第{page_no}页：{exc}")
                continue
            before = len(transactions)
            row_parts = []
            for line in body:
                cells = _cells(line, columns, cuts)
                present = {field for field, value in cells.items() if value}
                top = min(char["top"] for char in line)
                row_parts.append((top, cells, present <= CONTINUATION_FIELDS, max(c["size"] for c in line)))
            anchors = [(top, cells) for top, cells, continuation, _ in row_parts if not continuation]
            text_parts = {top: {field: [(top, value)] for field, value in cells.items() if value}
                          for top, cells in anchors}
            for top, cells, continuation, size in row_parts:
                if not continuation:
                    continue
                candidates = sorted(anchors, key=lambda item: abs(item[0] - top))
                if (not candidates or abs(candidates[0][0] - top) > size * 2.2
                        or (len(candidates) > 1 and abs(abs(candidates[0][0] - top) - abs(candidates[1][0] - top)) < .2)):
                    errors.append(f"第{page_no}页距页顶{top:.1f}处续行归属不明确")
                    continue
                anchor_top, _target = candidates[0]
                for field, value in cells.items():
                    if value:
                        text_parts[anchor_top].setdefault(field, []).append((top, value))
            for row_no, (top, cells) in enumerate(anchors, 1):
                for field, parts in text_parts[top].items():
                    cells[field] = "\n".join(value for _, value in sorted(parts))
                try:
                    transaction = _transaction(cells, path, page_no)
                    transaction.source_row = row_no
                    transactions.append(transaction)
                except ValueError as exc:
                    errors.append(f"第{page_no}页第{row_no}行（距页顶{top:.1f}）未识别：{exc}")
            carried = re.search(rf"上页余额\s*[：:]?\s*{AMOUNT}", text)
            if page_no > 1 and carried:
                if before == 0 or transactions[before - 1].balance != Decimal(carried.group(1).replace(",", "")):
                    errors.append(f"第{page_no}页上页余额与上一页末笔不一致")
    if not seen_header:
        return None
    extraction = StatementExtraction(
        source_path=path, bank_name="", account_number="", period_start=None, period_end=None,
        page_count=page_count, extraction_method=EXTRACTOR_LABEL, transactions=transactions,
        declared_count=None, declared_debit=None, declared_credit=None, errors=errors,
        serial_number_required=serial_required,
        control_pages=metadata_texts,
    )
    _metadata(extraction, metadata_texts)
    extraction.text_rows_complete = not extraction.errors
    if not serial_required:
        extraction.warnings.append("原件无流水号列，流水号保留空值；票据号单独保留，按来源文件、页码及行序追溯")
    if transactions:
        extraction.period_start = min(tx.occurred_at.date() for tx in transactions)
        extraction.period_end = max(tx.occurred_at.date() for tx in transactions)
    for tx in transactions:
        tx.bank_name, tx.account_number = extraction.bank_name, extraction.account_number
        tx.period_start, tx.period_end = extraction.period_start, extraction.period_end
    return extraction
