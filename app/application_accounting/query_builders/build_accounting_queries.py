from __future__ import annotations
from typing import Optional

from sqlalchemy import select, false, func, case, cast, String
from sqlalchemy.orm import Session, aliased

from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, AccountAccessPolicy
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, CostCenter, Account
)
from app.application_org.models.company import Branch, Company


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
