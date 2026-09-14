"""读取原件的控制余额与账期，并检查本批次的期间衔接。"""
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pdfplumber

AMOUNT = r"([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\d)"
DATE = r"(\d{4}[-/年]?\d{2}[-/月]?\d{2}日?)"
CONTROL_LABELS = {"opening_balance": "期初余额", "closing_balance": "期末余额", "statement_start": "账期开始日", "statement_end": "账期结束日", "currency": "币种"}
CONTROL_FIELDS = tuple(CONTROL_LABELS)


def _date(text):
    digits = re.sub(r"\D", "", text)
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))


def preserve_controls(extraction, previous):
    """回退可以修正交易，不能悄悄丢掉已取得的独立控制数。"""
    if previous is None:
        return
    for key in CONTROL_FIELDS:
        old, new = getattr(previous, key), getattr(extraction, key)
        if old not in (None, ""):
            if new not in (None, "") and old != new:
                extraction.errors.append(f"不同读取方式的{CONTROL_LABELS[key]}不一致，需核对原件")
            setattr(extraction, key, old)
    for key in ("opening_page", "closing_page", "period_page"):
        if getattr(previous, key):
            setattr(extraction, key, getattr(previous, key))


def enrich_from_pages(extraction, pages):
    patterns = {
        "opening_balance": rf"(?:期初余额|期初结余|上期余额|上期结余|账单期初余额)\s*[：:]?\s*{AMOUNT}",
        "closing_balance": rf"(?:本对账期末余额|期末余额|期末结余|账单期末余额)\s*[：:]?\s*{AMOUNT}",
        "statement_start": rf"(?:账单开始日期|起始日期|开始日期|对账开始日)\s*[：:]?\s*{DATE}",
        "statement_end": rf"(?:账单结束日期|截止日期|结束日期|对账结束日)\s*[：:]?\s*{DATE}",
        "currency": r"(?:币种|货币)\s*[：:]?\s*(人民币(?:\s*\(CNY\))?|CNY|RMB|美元|USD|港币|HKD|欧元|EUR)",
    }
    for page_no, text in enumerate(pages, 1):
        period = re.search(rf"(?:起止日期|账单所属期间|对账期间)\s*[：:]?\s*{DATE}(?:\s*(?:-|至|到)\s*|\s+){DATE}", text)
        if period:
            try:
                start, end = _date(period.group(1)), _date(period.group(2))
                if ((extraction.statement_start and extraction.statement_start != start)
                        or (extraction.statement_end and extraction.statement_end != end)):
                    extraction.errors.append(f"第{page_no}页账期与其他页不一致")
                else:
                    extraction.statement_start, extraction.statement_end = start, end
                    extraction.period_page = page_no
            except ValueError:
                extraction.errors.append(f"第{page_no}页起止日期无效")
        for key, pattern in patterns.items():
            matches = list(re.finditer(pattern, text))
            if key == "opening_balance" and page_no == 1 and not matches:
                matches = list(re.finditer(rf"上页余额\s*[：:]?\s*{AMOUNT}", text))
            # 中国银行首张页面的承前页余额是本账期期初，其余页不能当期初。
            if key == "opening_balance" and page_no == 1 and not matches and "中国银行" in text:
                matches = list(re.finditer(rf"承前页余额\s*[：:]?\s*{AMOUNT}", text))
            for match in matches:
                raw = match.group(1)
                if key.endswith("balance"):
                    value = Decimal(raw.replace(",", ""))
                elif key.startswith("statement"):
                    try:
                        value = _date(raw)
                    except ValueError:
                        extraction.errors.append(f"第{page_no}页对账日期无效")
                        continue
                else:
                    value = {"人民币": "CNY", "RMB": "CNY", "美元": "USD", "港币": "HKD", "欧元": "EUR"}.get(raw, raw)
                    if raw.startswith("人民币"):
                        value = "CNY"
                existing = getattr(extraction, key)
                if existing not in (None, "") and existing != value:
                    extraction.errors.append(f"第{page_no}页{CONTROL_LABELS[key]}与已有控制信息不一致")
                    continue
                setattr(extraction, key, value)
                if key.endswith("balance"):
                    setattr(extraction, "opening_page" if key.startswith("opening") else "closing_page", page_no)
                elif key.startswith("statement"):
                    extraction.period_page = page_no
    return extraction


def read_control_pages(path):
    try:
        with pdfplumber.open(path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except (OSError, ValueError):
        return []


LINK_HEADERS = ["银行名称", "账号", "币种", "前份文件", "后份文件", "前期开始", "前期结束",
                "后期开始", "后期结束", "前期期末余额", "后期期初余额", "余额差额", "检查结果"]


def statement_links(batch):
    rows, groups = [], defaultdict(list)
    def row(a, b=None, result="", difference=None):
        return dict(zip(LINK_HEADERS, [
            a.bank_name, a.account_number, a.currency, str(a.source_path),
            str(b.source_path) if b else "", a.statement_start, a.statement_end,
            b.statement_start if b else None, b.statement_end if b else None,
            a.closing_balance, b.opening_balance if b else None, difference, result]))
    for statement in batch.statements:
        e = statement.extraction
        if e is None:
            rows.append(dict(zip(LINK_HEADERS, ["", "", "", str(statement.source_path), "", None, None, None, None, None, None, None, "未检查，未取得对账单"])))
            continue
        if not e.bank_name or not e.account_number or re.search(r"[*＊xX…]", e.account_number) or not e.currency:
            rows.append(row(e, result="未检查，银行、完整账号或币种不明确"))
        elif not e.statement_start or not e.statement_end:
            rows.append(row(e, result="未检查，原件未注明完整账期"))
        elif e.statement_start > e.statement_end:
            rows.append(row(e, result="账期起止日期倒置"))
        else:
            groups[(e.bank_name.strip(), e.account_number.strip(), e.currency)].append(e)
    for group in groups.values():
        group.sort(key=lambda e: (e.statement_start, e.statement_end, str(e.source_path)))
        if len(group) == 1:
            rows.append(row(group[0], result="未检查，本次仅一份明确账期的对账单"))
            continue
        previous = group[0]
        for current in group[1:]:
            difference = None
            if current.statement_start <= previous.statement_end:
                result = "期间重叠，未作余额衔接判断"
            elif current.statement_start != previous.statement_end + timedelta(days=1):
                result = "期间缺期，未作余额衔接判断"
            elif previous.closing_balance is None or current.opening_balance is None:
                result = "未检查，缺少前期期末或后期期初余额"
            else:
                difference = current.opening_balance - previous.closing_balance
                result = "通过" if difference == 0 else "余额衔接不一致"
            rows.append(row(previous, current, result, difference))
            # 保留已覆盖的最远期末，避免嵌套账期造成虚假的缺口。
            if current.statement_end > previous.statement_end:
                previous = current
    return rows
