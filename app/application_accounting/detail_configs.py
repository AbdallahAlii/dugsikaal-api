
from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs

from app.application_accounting.chart_of_accounts.finance_model import (
    ExpenseType,
    Expense,
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear,
    CostCenter,
    Account,
    JournalEntry,
    PeriodClosingVoucher,
)
from app.application_accounting.query_builders.detail_builders import (
    # resolvers
    resolve_mop_by_name,
    resolve_fiscal_year_by_name,
    resolve_cost_center_by_name,
    resolve_account_by_name,
    resolve_expense_type_by_name,
    resolve_expense_by_code,
    resolve_payment_by_code,
    resolve_journal_entry_by_code,
    resolve_journal_entry_id_strict,
    resolve_pcv_by_code,
    resolve_pcv_id_strict,
    # loaders
    load_mode_of_payment,
    load_fiscal_year,
    load_cost_center,
    load_account,
    load_expense_type,
    load_expense,
    load_payment,
    load_journal_entry,
    load_period_closing_voucher,
)
from app.application_accounting.chart_of_accounts.account_policies import ModeOfPayment
from app.application_accounting.chart_of_accounts.finance_model import PaymentEntry

ACCOUNTING_DETAIL_CONFIGS = {
    "modes_of_payment": DetailConfig(
        permission_tag="Mode of Payment",
        loader=load_mode_of_payment,
        resolver_map={"name": resolve_mop_by_name},
        cache_enabled=True,
        cache_ttl=3600,
    ),
    "fiscal_years": DetailConfig(
        permission_tag="Fiscal Year",
        loader=load_fiscal_year,
        resolver_map={"name": resolve_fiscal_year_by_name},
        cache_enabled=True,
        cache_ttl=86400,
    ),
    "cost_centers": DetailConfig(
        permission_tag="Cost Center",
        loader=load_cost_center,
        resolver_map={"name": resolve_cost_center_by_name},
        cache_enabled=True,
        cache_ttl=1800,
    ),
    "accounts": DetailConfig(
        permission_tag="Account",
        loader=load_account,
        resolver_map={"name": resolve_account_by_name},
        cache_enabled=True,
        cache_ttl=7200,
    ),
    "expense_types": DetailConfig(
        permission_tag="Expense Type",
        loader=load_expense_type,
        resolver_map={"name": resolve_expense_type_by_name},
        cache_enabled=True,
        cache_ttl=86400,
    ),
    "expenses": DetailConfig(
        permission_tag="Expense",
        loader=load_expense,
        resolver_map={"code": resolve_expense_by_code},
        cache_enabled=True,
        cache_ttl=1800,
    ),
    "payments": DetailConfig(
        permission_tag="PaymentEntry",
        loader=load_payment,
        resolver_map={"code": resolve_payment_by_code},
        cache_enabled=False,
    ),
    "journal_entries": DetailConfig(
        permission_tag="JournalEntry",
        loader=load_journal_entry,
        resolver_map={
            "code": resolve_journal_entry_by_code,
            "id": resolve_journal_entry_id_strict,
        },
        cache_enabled=False,
        default_by="code",
    ),
    "period_closing_vouchers": DetailConfig(
        permission_tag="Period Closing Voucher",
        loader=load_period_closing_voucher,
        resolver_map={
            "code": resolve_pcv_by_code,
            "id": resolve_pcv_id_strict,
        },
        cache_enabled=False,
        default_by="code",
    ),
}


def register_accounting_detail_configs() -> None:
    register_detail_configs("accounting", ACCOUNTING_DETAIL_CONFIGS)
