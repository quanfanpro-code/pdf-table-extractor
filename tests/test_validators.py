from decimal import Decimal

from app.validators import validate_statement


def test_valid_statement_passes(sample_extraction):
    report = validate_statement(sample_extraction)

    assert report.status == "通过"
    assert report.actual_count == 2
    assert report.actual_debit == Decimal("25.00")
    assert report.actual_credit == Decimal("100.00")
    assert report.errors == []


def test_balance_break_is_rejected(sample_extraction):
    sample_extraction.transactions[1].balance += Decimal("1.00")

    report = validate_statement(sample_extraction)

    assert report.status == "核对失败"
    assert report.balance_break_rows == [2]
    assert any("连续余额" in error for error in report.errors)


def test_zero_statement_passes(zero_extraction):
    report = validate_statement(zero_extraction)

    assert report.status == "零交易通过"
    assert report.errors == []


def test_declared_count_mismatch_is_rejected(sample_extraction):
    sample_extraction.declared_count = 3

    report = validate_statement(sample_extraction)

    assert report.status == "核对失败"
    assert any("声明笔数=3，实际笔数=2" in error for error in report.errors)


def test_declared_amount_mismatch_is_rejected(sample_extraction):
    sample_extraction.declared_debit = Decimal("26.00")

    report = validate_statement(sample_extraction)

    assert report.status == "核对失败"
    assert any("借方合计" in error for error in report.errors)


def test_missing_serial_number_is_rejected(sample_extraction):
    sample_extraction.transactions[0].serial_number = ""

    report = validate_statement(sample_extraction)

    assert report.status == "核对失败"
    assert any("第1笔流水号为空" in error for error in report.errors)
