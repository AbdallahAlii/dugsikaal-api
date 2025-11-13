from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, func, case, cast, String
from sqlalchemy.orm import Session, aliased

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, AccountAccessPolicy
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, CostCenter, Account, PartyTypeEnum
)
from app.application_org.models.company import Branch, Company
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType, ExpenseItem,Expense
from app.application_accounting.chart_of_accounts.models import Account, AccountTypeEnum  # adjust path if different
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType,PaymentEntry
from app.application_parties.parties_models import Party,PartyRoleEnum
from app.application_hr.models.hr import Employee,EmployeeAssignment

def _ymd(col):
    """Render a date-only ISO string (YYYY-MM-DD) for UI."""
    return func.to_char(col, 'YYYY-MM-DD')


def _is_super_admin(ctx: AffiliationContext) -> bool:
    roles = getattr(ctx, "roles", []) or []
    return "Super Admin" in roles


def _is_company_owner(ctx: AffiliationContext) -> bool:
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    return getattr(ctx, "is_system_admin", False) or _is_super_admin(ctx) or _is_company_owner(ctx)


# ───────────────────────── Modes of Payment (LIST) ─────────────────────────
def build_modes_of_payment_query(session: Session, context: AffiliationContext):
    """
    Clean list payload:
      id, name, type (enum string), status (bool), company_name
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(ModeOfPayment.id).where(false())

    M = ModeOfPayment
    C = Company

    q = (
        select(
            M.id.label("id"),
            M.name.label("name"),
            M.type.label("type"),
            M.enabled.label("status"),
            C.name.label("company_name"),
        )
        .select_from(M)
        .join(C, C.id == M.company_id)
        .where(M.company_id == co_id)
    )
    return q


# ───────────────────────── Fiscal Years (LIST) ─────────────────────────
def build_fiscal_years_query(session: Session, context: AffiliationContext):
    """
    Clean list payload:
      id, year_name, year_start_date, year_end_date, status, company_name
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(FiscalYear.id).where(false())

    FY = FiscalYear
    C = Company

    q = (
        select(
            FY.id.label("id"),
            FY.name.label("year_name"),
            _ymd(FY.start_date).label("year_start_date"),
            _ymd(FY.end_date).label("year_end_date"),
            FY.status.label("status"),
            C.name.label("company_name"),
        )
        .select_from(FY)
        .join(C, C.id == FY.company_id)
        .where(FY.company_id == co_id)
    )
    return q


# ───────────────────────── Cost Centers (LIST) ─────────────────────────
def build_cost_centers_query(session: Session, context: AffiliationContext):
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(CostCenter.id).where(false())

    CC = CostCenter
    B = Branch
    C = Company

    q = (
        select(
            CC.id.label("id"),
            CC.name.label("name"),
            CC.enabled.label("status"),
            B.name.label("branch_name"),
            C.name.label("company_name"),
            CC.branch_id.label("branch_id"),
        )
        .select_from(CC)
        .join(C, C.id == CC.company_id)
        .join(B, B.id == CC.branch_id)
        .where(CC.company_id == co_id)
    )

    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(CC.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q


# ───────────────────────── Accounts (LIST) ─────────────────────────
def build_accounts_query(session: Session, context: AffiliationContext):
    """
    ERP-style listing with a display ID: "<code> - <name> - D/C"
    Filters by account_type and report_type are supported in ListConfig.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Account.id).where(false())

    A = Account
    PA = aliased(Account)  # IMPORTANT: real alias for parent
    C = Company

    # D/C letter from enum value (assumed DB stores 'DEBIT'/'CREDIT')
    dc_letter = case(
        (cast(A.debit_or_credit, String) == 'DEBIT', 'D'),
        else_='C'
    )

    q = (
        select(
            A.id.label("id"),
            func.concat(A.code, ' - ', A.name, ' - ', dc_letter).label("display_id"),
            A.name.label("account_name"),
            A.code.label("account_number"),
            A.account_type.label("account_type"),
            A.report_type.label("report_type"),
            A.is_group.label("is_group"),
            A.debit_or_credit.label("debit_or_credit"),
            A.enabled.label("enabled"),
            C.name.label("company_name"),
            A.parent_account_id.label("parent_account_id"),
            PA.name.label("parent_account_name"),
            PA.code.label("parent_account_code"),
        )
        .select_from(A)
        .join(C, C.id == A.company_id)
        .outerjoin(PA, PA.id == A.parent_account_id)
        .where(A.company_id == co_id)
    )
    return q


# ───────────────────── Account Access Policies (LIST) ─────────────────────
def build_account_access_policies_query(session: Session, context: AffiliationContext):
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(AccountAccessPolicy.id).where(false())

    AAP = AccountAccessPolicy
    M = ModeOfPayment
    ACC = Account
    B = Branch
    C = Company

    q = (
        select(
            AAP.id.label("id"),
            AAP.enabled.label("status"),
            AAP.role.label("role"),
            AAP.mode_of_payment_id.label("mode_of_payment_id"),
            M.name.label("mode_of_payment_name"),
            AAP.account_id.label("account_id"),
            ACC.name.label("account_name"),
            ACC.code.label("account_code"),
            AAP.user_id.label("user_id"),
            AAP.department_id.label("department_id"),
            AAP.branch_id.label("branch_id"),
            B.name.label("branch_name"),
            C.name.label("company_name"),
        )
        .select_from(AAP)
        .join(C, C.id == AAP.company_id)
        .join(M, M.id == AAP.mode_of_payment_id)
        .join(ACC, ACC.id == AAP.account_id)
        .outerjoin(B, B.id == AAP.branch_id)
        .where(AAP.company_id == co_id)
    )

    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where((AAP.branch_id.is_(None)) | (AAP.branch_id.in_(branch_ids)))
        else:
            q = q.where(AAP.branch_id.is_(None))

    return q


# ───────────────────────── Expenses (LIST) ─────────────────────────
def build_expenses_query(session: Session, context: AffiliationContext):
    """
    Minimal list for Expense headers (direct expense):
      id, code, status, expense_type_name, amount

    Notes:
      * expense_type_name = the single type name if all items share one; otherwise "Mixed".
      * posting_date, company/branch names, etc. are available in the *detail* endpoint.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Expense.id).where(false())

    E = Expense
    EI = ExpenseItem
    ET = ExpenseType

    agg = (
        select(
            EI.expense_id.label("expense_id"),
            func.count(func.distinct(EI.expense_type_id)).label("type_count"),
            func.min(EI.expense_type_id).label("single_type_id"),
        )
        .group_by(EI.expense_id)
        .subquery("ei_agg")
    )

    q = (
        select(
            E.id.label("id"),
            E.code.label("code"),
            E.doc_status.label("status"),
            E.total_amount.label("amount"),
            case((agg.c.type_count == 1, ET.name), else_="Mixed").label("expense_type_name"),
        )
        .select_from(E)
        .outerjoin(agg, agg.c.expense_id == E.id)
        .outerjoin(ET, ET.id == agg.c.single_type_id)
        .where(E.company_id == co_id)
    )
    return q
# ───────────────────────── Expense Types (LIST) ─────────────────────────
def build_expense_types_query(session: Session, context: AffiliationContext):
    """
    Minimal list for Expense Types:
      id, name, enabled

    Full default account info is provided by the *detail* loader.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(ExpenseType.id).where(false())

    ET = ExpenseType

    q = (
        select(
            ET.id.label("id"),
            ET.name.label("name"),
            ET.enabled.label("enabled"),
        )
        .select_from(ET)
        .where(ET.company_id == co_id)
    )
    return q


def build_payments_query(session: Session, context: AffiliationContext):
    """
    Clean list payload for Payment Entry - ERP-style minimal fields
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PaymentEntry.id).where(false())

    PE = PaymentEntry
    MOP = ModeOfPayment

    # Get party name based on party_type - optimized single query approach
    party_name_case = case(
        # Customer
        (PE.party_type == PartyTypeEnum.CUSTOMER,
         select(Party.name)
         .where(Party.id == PE.party_id)
         .scalar_subquery()),
        # Supplier
        (PE.party_type == PartyTypeEnum.SUPPLIER,
         select(Party.name)
         .where(Party.id == PE.party_id)
         .scalar_subquery()),
        # Employee
        (PE.party_type == PartyTypeEnum.EMPLOYEE,
         select(Employee.full_name)
         .where(Employee.id == PE.party_id)
         .scalar_subquery()),
        else_=None
    ).label("party_name")

    q = (
        select(
            PE.id.label("id"),
            PE.code.label("code"),
            PE.payment_type.label("payment_type"),
            PE.doc_status.label("status"),
            party_name_case,
            PE.paid_amount.label("paid_amount"),
            _ymd(PE.posting_date).label("posting_date"),
            MOP.name.label("mode_of_payment_name"),
            # Removed company_name and branch_name from list - not needed
        )
        .select_from(PE)
        .outerjoin(MOP, MOP.id == PE.mode_of_payment_id)
        .where(PE.company_id == co_id)
    )

    # Branch scope filtering
    if not _has_company_wide_access(context):
        branch_ids = list(getattr(context, "branch_ids", []) or [])
        if branch_ids:
            q = q.where(PE.branch_id.in_(branch_ids))
        else:
            q = q.where(false())

    return q