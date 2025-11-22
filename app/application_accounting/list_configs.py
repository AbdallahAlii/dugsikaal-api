from __future__ import annotations

from app.application_doctypes.core_lists.config import ListConfig, register_list_configs
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType, ExpenseItem,Expense
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, AccountAccessPolicy
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, CostCenter, Account,JournalEntry
)
from app.application_accounting.query_builders.build_accounting_queries import (
    build_modes_of_payment_query,
    build_fiscal_years_query,
    build_cost_centers_query,
    build_accounts_query,
    build_account_access_policies_query, build_expenses_query,
    build_expense_types_query, build_payments_query,  # keep if you still expose AAP lists
)
from app.application_org.models.company import Branch, Company
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType,PaymentEntry
from app.application_stock.query_builders.build_journal_entries_query import build_journal_entries_query
from app.auth.models.users import User
ACCOUNTING_LIST_CONFIGS = {
    # ─────────────────── Modes of Payment ───────────────────
    "modes_of_payment": ListConfig(
        permission_tag="Mode of Payment",
        query_builder=build_modes_of_payment_query,
        search_fields=[ModeOfPayment.name],
        sort_fields={
            "name": ModeOfPayment.name,
            "type": ModeOfPayment.type,
            "enabled": ModeOfPayment.enabled,
            "id": ModeOfPayment.id,
        },
        filter_fields={
            "company_id": ModeOfPayment.company_id,
            "type": ModeOfPayment.type,
            "enabled": ModeOfPayment.enabled,
        },
        cache_enabled=True,
        cache_ttl=3600,
    ),

    # ─────────────────── Fiscal Years ───────────────────
    "fiscal_years": ListConfig(
        permission_tag="Fiscal Year",
        query_builder=build_fiscal_years_query,
        search_fields=[FiscalYear.name],
        sort_fields={
            "year_name": FiscalYear.name,
            "year_start_date": FiscalYear.start_date,
            "year_end_date": FiscalYear.end_date,
            "status": FiscalYear.status,
            "id": FiscalYear.id,
        },
        filter_fields={
            "company_id": FiscalYear.company_id,
            "status": FiscalYear.status,
            "year_start_date": FiscalYear.start_date,
            "year_end_date": FiscalYear.end_date,
        },
        cache_enabled=True,
        cache_ttl=86400,
    ),

    # ─────────────────── Cost Centers ───────────────────
    "cost_centers": ListConfig(
        permission_tag="Cost Center",
        query_builder=build_cost_centers_query,
        search_fields=[CostCenter.name],
        sort_fields={
            "name": CostCenter.name,
            "branch_id": CostCenter.branch_id,
            "enabled": CostCenter.enabled,
            "id": CostCenter.id,
        },
        filter_fields={
            "company_id": CostCenter.company_id,
            "branch_id": CostCenter.branch_id,
            "enabled": CostCenter.enabled,
        },
        cache_enabled=True,
        cache_ttl=1800,
    ),

    # ─────────────────── Accounts ───────────────────
    "accounts": ListConfig(
        permission_tag="Account",
        query_builder=build_accounts_query,
        search_fields=[Account.name, Account.code],
        sort_fields={
            "account_number": Account.code,
            "account_name": Account.name,
            "account_type": Account.account_type,
            "enabled": Account.enabled,       # ← replaced old status
            "id": Account.id,
        },
        filter_fields={
            "company_id": Account.company_id,
            "account_type": Account.account_type,
            "report_type": Account.report_type,
            "is_group": Account.is_group,
            "enabled": Account.enabled,       # ← replaced old status
        },
        cache_enabled=True,
        cache_ttl=7200,
    ),

    # ─────────────────── Account Access Policies (optional) ───────────────────
    "account_access_policies": ListConfig(
        permission_tag="Account Access Policy",
        query_builder=build_account_access_policies_query,
        search_fields=[AccountAccessPolicy.role, "mode_of_payment_name", "account_name"],
        sort_fields={
            "id": AccountAccessPolicy.id,
            "role": AccountAccessPolicy.role,
            "enabled": AccountAccessPolicy.enabled,
        },
        filter_fields={
            "company_id": AccountAccessPolicy.company_id,
            "mode_of_payment_id": AccountAccessPolicy.mode_of_payment_id,
            "account_id": AccountAccessPolicy.account_id,
            "role": AccountAccessPolicy.role,
            "branch_id": AccountAccessPolicy.branch_id,
            "enabled": AccountAccessPolicy.enabled,
        },
        cache_enabled=True,
        cache_ttl=900,
    ),

    # ─────────────────── Expense Types ───────────────────
    "expense_types": ListConfig(
        permission_tag="Expense Type",
        query_builder=build_expense_types_query,
        search_fields=[ExpenseType.name, ExpenseType.description],
        sort_fields={
            "name": ExpenseType.name,
            "enabled": ExpenseType.enabled,
            "id": ExpenseType.id,
        },
        filter_fields={
            "company_id": ExpenseType.company_id,
            "enabled": ExpenseType.enabled,
            # optional UI switch: ensure_has_default_account handled in builder if you add it later
        },
        cache_enabled=True,
        cache_ttl=86400,  # master rarely changes → cache longer
    ),

    # ─────────────────── Expenses (Direct Expense) ───────────────────
    "expenses": ListConfig(
        permission_tag="Expense",
        query_builder=build_expenses_query,
        search_fields=[Expense.code, Expense.remarks],
        sort_fields={
            "code": Expense.code,
            "posting_date": Expense.posting_date,
            "amount": Expense.total_amount,
            "status": Expense.doc_status,
            "id": Expense.id,
        },
        filter_fields={
            "company_id": Expense.company_id,
            "branch_id": Expense.branch_id,
            "doc_status": Expense.doc_status,
            "posting_date": Expense.posting_date,
        },
        cache_enabled=True,
        cache_ttl=600,  # transactions change more often
    ),
# ─────────────────── Payment Entries ───────────────────
"payments": ListConfig(
    permission_tag="PaymentEntry",
    query_builder=build_payments_query,
    search_fields=[PaymentEntry.code, "party_name", "mode_of_payment_name"],
    sort_fields={
        "code": PaymentEntry.code,
        "payment_type": PaymentEntry.payment_type,
        "status": PaymentEntry.doc_status,
        "posting_date": PaymentEntry.posting_date,
        "paid_amount": PaymentEntry.paid_amount,
        "id": PaymentEntry.id,
    },
    filter_fields={
        "company_id": PaymentEntry.company_id,
        "branch_id": PaymentEntry.branch_id,
        "doc_status": PaymentEntry.doc_status,
        "payment_type": PaymentEntry.payment_type,
        "posting_date": PaymentEntry.posting_date,
        "party_type": PaymentEntry.party_type,
        "mode_of_payment_id": PaymentEntry.mode_of_payment_id,
    },
    cache_enabled=False,
),
    "journal_entries": ListConfig(
        permission_tag="Journal Entry",
        query_builder=build_journal_entries_query,
        search_fields=[
            JournalEntry.code,
            Branch.name,
            Company.name,
            User.username,
        ],
        sort_fields={
            "posting_date": JournalEntry.posting_date,
            "created_at": JournalEntry.created_at,
            "code": JournalEntry.code,
            "status": JournalEntry.doc_status,
            "entry_type": JournalEntry.entry_type,
            "location": Branch.name,
            "id": JournalEntry.id,
        },
        filter_fields={
            "company_id": JournalEntry.company_id,
            "branch_id": JournalEntry.branch_id,
            "status": JournalEntry.doc_status,
            "entry_type": JournalEntry.entry_type,
            "posting_date": JournalEntry.posting_date,
            "created_by_id": JournalEntry.created_by_id,
        },
        cache_enabled=False,
    ),
}

def register_module_lists() -> None:
    register_list_configs("accounting", ACCOUNTING_LIST_CONFIGS)
