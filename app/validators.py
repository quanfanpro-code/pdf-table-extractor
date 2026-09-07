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


    control_checks = {}
    def check(label, expected, actual, reason):
        difference = actual - expected if expected is not None and actual is not None else None
        state = "未检查" if difference is None else ("通过" if difference == 0 else "不一致")
        control_checks[label] = dict(status=state, expected=expected, actual=actual, difference=difference,
                                     reason=reason if difference is None else "")
        if state == "不一致":
            errors.append(f"{extraction.source_path.name}：{label}不一致，应为={expected:.2f}，实际={actual:.2f}，差额={difference:.2f}")

    opening, closing = extraction.opening_balance, extraction.closing_balance
    check("期初期末", opening - actual_debit + actual_credit if opening is not None else None,
          closing, "缺少原件期初或期末余额")
    first = transactions[0] if transactions else None
    last = transactions[-1] if transactions else None
    check("首笔余额", opening - first.debit + first.credit if opening is not None and first else None,
          first.balance if first else None, "缺少原件期初余额或本期没有交易")
    check("末笔余额", closing, last.balance if last else None, "缺少原件期末余额或本期没有交易")

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
        control_checks=control_checks,
        errors=errors,
    )
