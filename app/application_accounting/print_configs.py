from __future__ import annotations

from app.application_print.registry.print_registry import (
    PrintConfig,
    register_print_configs,
)
from app.application_accounting.query_builders.detail_builders import (
    load_payment,
    load_expense,
    load_journal_entry,
    load_period_closing_voucher,
)


ACCOUNTING_PRINT_CONFIGS: dict[str, PrintConfig] = {
    # URL example: /print/accounting/payments/PAY-0001
    "payments": PrintConfig(
        permission_tag="PaymentEntry",
        doctype="PaymentEntry",  # ← NO SPACE, must match print_formats.doctype
        loader=load_payment,
    ),
    # URL example: /print/accounting/expenses/EXP-0001
    "expenses": PrintConfig(
        permission_tag="Expense",
        doctype="Expense",
        loader=load_expense,
    ),
    # URL example: /print/accounting/journal_entries/JV-0001
    "journal_entries": PrintConfig(
        permission_tag="JournalEntry",
        doctype="JournalEntry",
        loader=load_journal_entry,
    ),
    # URL example: /print/accounting/period_closing_vouchers/PCV-0001
    "period_closing_vouchers": PrintConfig(
        permission_tag="Period Closing Voucher",
        doctype="PeriodClosingVoucher",
        loader=load_period_closing_voucher,
    ),
}


def register_accounting_print_configs() -> None:
    """
    Called by core.module_autoreg via register_module_prints().
    """
    register_print_configs("accounting", ACCOUNTING_PRINT_CONFIGS)
