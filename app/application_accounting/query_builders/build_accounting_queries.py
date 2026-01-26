from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, func, case, cast, String
from sqlalchemy.orm import Session, aliased

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment,
    AccountAccessPolicy,
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear,
    CostCenter,
    Account,
    AccountTypeEnum,
    PartyTypeEnum,
    PeriodClosingVoucher,
)
from app.application_org.models.company import Branch, Company
from app.application_accounting.chart_of_accounts.finance_model import (
    ExpenseType,
    ExpenseItem,
    Expense,
    PaymentEntry,
)
from app.application_parties.parties_models import Party
from app.application_hr.models.hr import Employee


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ymd(col):
    """Render a date-only ISO string (YYYY-MM-DD) for UI."""
    return func.to_char(col, "YYYY-MM-DD")


def _is_super_admin(ctx: AffiliationContext) -> bool:
    roles = getattr(ctx, "roles", []) or []
    # Keep case-insensitive just in case
    return any((str(r) or "").lower() == "super admin" for r in roles)


def _is_company_owner(ctx: AffiliationContext) -> bool:
    affiliations = getattr(ctx, "affiliations", []) or []
    for aff in affiliations:
        # Primary + branch_id is NULL → “company-level” affiliation
        if getattr(aff, "is_primary", False) and getattr(aff, "branch_id", None) is None:
            return True
    return False


def _has_company_wide_access(ctx: AffiliationContext) -> bool:
    """
    Kept for compatibility, but note:

    Your enforce-scope logic for transactional docs already lives in
    ensure_scope_by_ids / resolve_company_branch_and_scope.

    For LIST queries we now behave ERPNext-style:
      • Filter by company only.
      • All users of the same company see all branches for that company.
      • Other companies see nothing.

    So this helper is no longer used to *hide* branches for list queries.
    """
    return (
        bool(getattr(ctx, "is_system_admin", False))
        or _is_super_admin(ctx)
        or _is_company_owner(ctx)
    )


# ---------------------------------------------------------------------------
# Modes of Payment (LIST)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fiscal Years (LIST)
# ---------------------------------------------------------------------------

def build_fiscal_years_query(session: Session, context: AffiliationContext):
    """
    Clean list payload:
      id, name, start_date, end_date, status, is_short_year, company_name
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(FiscalYear.id).where(false())

    FY = FiscalYear
    C = Company

    q = (
        select(
            FY.id.label("id"),
            FY.name.label("name"),
            _ymd(FY.start_date).label("start_date"),
            _ymd(FY.end_date).label("end_date"),
            FY.status.label("status"),
            FY.is_short_year.label("is_short_year"),
            C.name.label("company_name"),
        )
        .select_from(FY)
        .join(C, C.id == FY.company_id)
        .where(FY.company_id == co_id)
    )
    return q



# ---------------------------------------------------------------------------
# Cost Centers (LIST)
# ---------------------------------------------------------------------------

def build_cost_centers_query(session: Session, context: AffiliationContext):
    """
    Company-level listing:
      • All users for this company can see cost centers for all branches.
      • Other companies see nothing.

    Row-level branch security is handled in the transactional services
    via ensure_scope_by_ids.
    """
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

    # No extra branch restriction: ERP-style company-wide visibility
    return q


# ---------------------------------------------------------------------------
# Accounts (LIST)
# ---------------------------------------------------------------------------

def build_accounts_query(session: Session, context: AffiliationContext):
    """
    ERP-style listing with a display ID: "<code> - <name> - D/C"
    Filters by account_type and report_type are supported in ListConfig.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Account.id).where(false())

    A = Account
    PA = aliased(Account)  # alias for parent
    C = Company

    # D/C letter from enum value (assumed DB stores 'DEBIT'/'CREDIT')
    dc_letter = case(
        (cast(A.debit_or_credit, String) == "DEBIT", "D"),
        else_="C",
    )

    q = (
        select(
            A.id.label("id"),
            func.concat(A.code, " - ", A.name, " - ", dc_letter).label("display_id"),
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


# ---------------------------------------------------------------------------
# Account Access Policies (LIST)
# ---------------------------------------------------------------------------

def build_account_access_policies_query(session: Session, context: AffiliationContext):
    """
    Company-level list:
      • All users for the company see all policies of that company.
      • If you later want branch restriction, you can reintroduce it.
    """
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

    # No branch filter here → company-wide visibility
    return q


# ---------------------------------------------------------------------------
# Expenses (LIST)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Expense Types (LIST)
# ---------------------------------------------------------------------------

def build_expense_types_query(session: Session, context: AffiliationContext):
    """
    Minimal list for Expense Types:
      id, name, enabled
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


# ---------------------------------------------------------------------------
# Payment Entries (LIST)
# ---------------------------------------------------------------------------

def build_payments_query(session: Session, context: AffiliationContext):
    """
    Clean list payload for Payment Entry - ERP-style minimal fields.

    Behavior:
      • Filter by company_id only.
      • ALL branches for that company are visible to users of that company.
      • Row-level scope for mutations/cancellations is enforced in services
        via ensure_scope_by_ids / resolve_company_branch_and_scope.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PaymentEntry.id).where(false())

    PE = PaymentEntry
    MOP = ModeOfPayment

    # Party name based on party_type - optimized single query approach
    party_name_case = case(
        # Customer
        (
            PE.party_type == PartyTypeEnum.CUSTOMER,
            select(Party.name).where(Party.id == PE.party_id).scalar_subquery(),
        ),
        # Supplier
        (
            PE.party_type == PartyTypeEnum.SUPPLIER,
            select(Party.name).where(Party.id == PE.party_id).scalar_subquery(),
        ),
        # Employee
        (
            PE.party_type == PartyTypeEnum.EMPLOYEE,
            select(Employee.full_name).where(Employee.id == PE.party_id).scalar_subquery(),
        ),
        else_=None,
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
        )
        .select_from(PE)
        .outerjoin(MOP, MOP.id == PE.mode_of_payment_id)
        .where(PE.company_id == co_id)
        .order_by(PE.posting_date.desc(), PE.id.desc())  # newest first, ERP-style
    )

    # No extra branch filter → all branches of this company
    return q


# ---------------------------------------------------------------------------
# Period Closing Vouchers (LIST)
# ---------------------------------------------------------------------------

def build_period_closing_vouchers_query(session: Session, context: AffiliationContext):
    """
    Minimal list for Period Closing Voucher:

      id,
      code,
      posting_date (YYYY-MM-DD),
      status,
      fiscal_year_name,
      total_profit_loss

    Detail endpoint will show journal entry, remarks, etc.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PeriodClosingVoucher.id).where(false())

    PCV = PeriodClosingVoucher
    FY = FiscalYear
    C = Company

    q = (
        select(
            PCV.id.label("id"),
            PCV.code.label("code"),
            _ymd(PCV.posting_date).label("posting_date"),
            PCV.doc_status.label("status"),
            FY.name.label("fiscal_year_name"),
            PCV.total_profit_loss.label("total_profit_loss"),
            C.name.label("company_name"),
        )
        .select_from(PCV)
        .join(FY, FY.id == PCV.closing_fiscal_year_id)
        .join(C, C.id == PCV.company_id)
        .where(PCV.company_id == co_id)
        .order_by(PCV.posting_date.desc(), PCV.id.desc())  # newest closing on top
    )
    return q
