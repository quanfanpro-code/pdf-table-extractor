from decimal import Decimal

from app.models import StatementExtraction, ValidationReport


def validate_statement(extraction: StatementExtraction) -> ValidationReport:
    transactions = extraction.transactions
    actual_count = len(transactions)
    actual_debit = sum((row.debit for row in transactions), Decimal("0.00"))
    actual_credit = sum((row.credit for row in transactions), Decimal("0.00"))
    errors = list(extraction.errors)
    balance_break_rows: list[int] = []

    if extraction.declared_count is None:
        errors.append(f"{extraction.source_path.name}：未取得对账单声明笔数")
    elif extraction.declared_count != actual_count:
        errors.append(
            f"{extraction.source_path.name}：笔数核对失败，"
            f"声明笔数={extraction.declared_count}，实际笔数={actual_count}"
        )

    if extraction.declared_debit is None:
        errors.append(f"{extraction.source_path.name}：未取得对账单借方合计")
    elif extraction.declared_debit != actual_debit:
        errors.append(
            f"{extraction.source_path.name}：借方合计核对失败，"
            f"声明值={extraction.declared_debit:.2f}，实际值={actual_debit:.2f}"
        )

    if extraction.declared_credit is None:
        errors.append(f"{extraction.source_path.name}：未取得对账单贷方合计")
    elif extraction.declared_credit != actual_credit:
        errors.append(
            f"{extraction.source_path.name}：贷方合计核对失败，"
            f"声明值={extraction.declared_credit:.2f}，实际值={actual_credit:.2f}"
        )

    for index, transaction in enumerate(transactions, start=1):
        if not transaction.serial_number.strip():
            errors.append(f"{extraction.source_path.name}：第{index}笔流水号为空")

        if index > 1:
            previous = transactions[index - 2]
            expected_balance = previous.balance - transaction.debit + transaction.credit
            if expected_balance != transaction.balance:
                balance_break_rows.append(index)
                errors.append(
                    f"{extraction.source_path.name}：第{index}笔连续余额核对失败，"
                    f"应为={expected_balance:.2f}，实际={transaction.balance:.2f}"
                )

    if errors:
        status = "核对失败"
    elif actual_count == 0:
        status = "零交易通过"
    else:
        status = "通过"

    return ValidationReport(
        status=status,
        actual_count=actual_count,
        actual_debit=actual_debit,
        actual_credit=actual_credit,
        balance_break_rows=balance_break_rows,
        errors=errors,
    )
