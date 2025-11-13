from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType, ExpenseItem,Expense
from app.application_accounting.query_builders.detail_builders import (
    # resolvers
    resolve_mop_by_name,
    resolve_fiscal_year_by_name,
    resolve_cost_center_by_name,
    resolve_account_by_name,
    # loaders
    load_mode_of_payment,
    load_fiscal_year,
    load_cost_center,
    load_account, load_expense_type, resolve_expense_type_by_name, resolve_expense_by_code, load_expense,
    resolve_payment_by_code, load_payment,
)

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
}

def register_accounting_detail_configs() -> None:
    register_detail_configs("accounting", ACCOUNTING_DETAIL_CONFIGS)
