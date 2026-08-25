from datetime import date, datetime
from decimal import Decimal

from app.extractors.minsheng import parse_footer, parse_page_words


def word(text: str, x0: float, top: float) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + len(text) * 7, "top": top, "bottom": top + 7}


def test_column_assignment_keeps_wrapped_fields_together():
    words = [
        word("2026/02/12", 22, 111),
        word("15:58:39", 22, 118),
        word("员工春节福利采购", 61.1, 111),
        word("网银凭证", 200.1, 111),
        word("13629821", 234.9, 111),
        word("0.00", 332.4, 111),
        word("1,008.00", 392.3, 111),
        word("132,249.95", 459.2, 111),
        word("313512026021", 498.2, 111),
        word("20150916202", 498.2, 118),
        word("东方鸿锐（成都）会展有限公司/650330267", 546, 111),
        word("中国民生银行股份有限公司成都分", 711, 111),
        word("行营业部", 711, 118),
    ]

    rows = parse_page_words(
        words,
        page_number=2,
        source_file="样本.pdf",
        account_number="650103833",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        page_height=595,
    )

    assert len(rows) == 1
    assert rows[0].occurred_at == datetime(2026, 2, 12, 15, 58, 39)
    assert rows[0].serial_number == "31351202602120150916202"
    assert rows[0].counterparty_bank == "中国民生银行股份有限公司成都分行营业部"
    assert rows[0].debit == Decimal("0.00")
    assert rows[0].credit == Decimal("1008.00")


def test_next_date_starts_a_new_transaction():
    words = [
        word("2026/02/12", 22, 111),
        word("15:58:39", 22, 118),
        word("第一笔", 61.1, 111),
        word("0.00", 332.4, 111),
        word("10.00", 392.3, 111),
        word("10.00", 459.2, 111),
        word("10001", 498.2, 111),
        word("2026/02/13", 22, 131),
        word("16:00:00", 22, 138),
        word("第二笔", 61.1, 131),
        word("5.00", 332.4, 131),
        word("0.00", 392.3, 131),
        word("5.00", 459.2, 131),
        word("10002", 498.2, 131),
    ]

    rows = parse_page_words(
        words,
        page_number=1,
        source_file="样本.pdf",
        account_number="650103833",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        page_height=595,
    )

    assert [row.summary for row in rows] == ["第一笔", "第二笔"]
    assert [row.serial_number for row in rows] == ["10001", "10002"]


def test_footer_totals_are_parsed_with_pdf_underscores():
    text = "借__方__发__生__总__额__:__1_,_2_3_4_._5_0 贷__方__发__生__总__额__:__2_0_._0_0 合__计__笔__数__:__3"

    count, debit, credit = parse_footer(text)

    assert count == 3
    assert debit == Decimal("1234.50")
    assert credit == Decimal("20.00")
