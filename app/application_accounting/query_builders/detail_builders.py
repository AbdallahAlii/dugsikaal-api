from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Models
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, ModeOfPaymentAccount
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, CostCenter, Account
)
from app.application_org.models.company import Company, Branch

APP_TZ = timezone(timedelta(hours=3))  # Africa/Mogadishu (+03:00)


def _iso_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    else:
        dt = dt.astimezone(APP_TZ)
    return dt.date().isoformat()


def _first_or_404(session: Session, stmt, label: str) -> dict:
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


def _enum_title(x) -> str:
    """Return a friendly title for python Enum or string values."""
    v = getattr(x, "value", x)
    if isinstance(v, str):
        return v.replace("_", " ").title()
    return str(v)


# ─────────────────────────── Resolvers (by name) ───────────────────────────

def resolve_mop_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    M = ModeOfPayment
    stmt = select(M.id, M.company_id).where((M.name == name) & (M.company_id == ctx.company_id))
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Mode of Payment not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)
    return int(row.id)


def resolve_fiscal_year_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    FY = FiscalYear
    stmt = select(FY.id, FY.company_id).where((FY.name == name) & (FY.company_id == ctx.company_id))
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Fiscal Year not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)
    return int(row.id)


def resolve_cost_center_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    CC = CostCenter
    stmt = select(CC.id, CC.company_id, CC.branch_id).where((CC.name == name) & (CC.company_id == ctx.company_id))
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Cost Center not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)


def resolve_account_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    A = Account
    row = s.execute(select(A.id, A.company_id).where((A.name == name) & (A.company_id == ctx.company_id))).first()
    if not row:
        raise NotFound("Account not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)
    return int(row.id)


# ─────────────────────────── Loaders (detail JSON) ───────────────────────────

def load_mode_of_payment(s: Session, ctx: AffiliationContext, mop_id: int) -> Dict[str, Any]:
    """Return MoP detail WITHOUT access_control block; friendly enum titles."""
    M, MA, ACC = ModeOfPayment, ModeOfPaymentAccount, Account

    # Header
    header_stmt = (
        select(
            M.id, M.name, M.type, M.enabled, M.company_id,
            Company.name.label("company_name")
        )
        .select_from(M)
        .join(Company, Company.id == M.company_id)
        .where(M.id == mop_id)
    )
    hdr = _first_or_404(s, header_stmt, "Mode of Payment")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    # Minimal accounts (id/code/name/is_default/enabled)
    accounts_stmt = (
        select(
            MA.id.label("id"),
            MA.account_id.label("account_id"),
            ACC.code.label("account_code"),
            ACC.name.label("account_name"),
            MA.is_default.label("is_default"),
            MA.enabled.label("enabled"),
        )
        .select_from(MA)
        .join(ACC, ACC.id == MA.account_id)
        .where(MA.mode_of_payment_id == mop_id)
        .order_by(MA.is_default.desc(), ACC.code.asc())
    )
    accounts = [dict(r) for r in s.execute(accounts_stmt).mappings().all()]

    return {
        "basic_details": {
            "id": hdr["id"],
            "name": hdr["name"],
            "type": _enum_title(hdr["type"]),  # e.g., "Cash"
            "status": bool(hdr["enabled"]),
            "company_name": hdr["company_name"],
        },
        "accounts": accounts
    }


def load_fiscal_year(s: Session, ctx: AffiliationContext, fiscal_year_id: int) -> Dict[str, Any]:
    FY = FiscalYear

    stmt = (
        select(
            FY.id, FY.name, FY.status,
            FY.start_date, FY.end_date,
            FY.is_short_year, FY.company_id,
            Company.name.label("company_name")
        )
        .select_from(FY)
        .join(Company, Company.id == FY.company_id)
        .where(FY.id == fiscal_year_id)
    )
    hdr = _first_or_404(s, stmt, "Fiscal Year")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    return {
        "basic_details": {
            "id": hdr["id"],
            "year_name": hdr["name"],
            "status": _enum_title(hdr["status"]),  # "Open", "Closed", etc.
            "year_start_date": _iso_date(hdr["start_date"]),
            "year_end_date": _iso_date(hdr["end_date"]),
            "is_short_year": bool(hdr["is_short_year"]),
            "company_name": hdr["company_name"],
        }
    }


def load_cost_center(s: Session, ctx: AffiliationContext, cost_center_id: int) -> Dict[str, Any]:
    CC = CostCenter

    stmt = (
        select(
            CC.id, CC.name, CC.enabled,
            CC.company_id, CC.branch_id,
            Company.name.label("company_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(CC)
        .join(Company, Company.id == CC.company_id)
        .join(Branch, Branch.id == CC.branch_id)
        .where(CC.id == cost_center_id)
    )
    hdr = _first_or_404(s, stmt, "Cost Center")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    return {
        "basic_details": {
            "id": hdr["id"],
            "name": hdr["name"],
            "status": bool(hdr["enabled"]),
            "company_name": hdr["company_name"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
        }
    }


def load_account(s: Session, ctx: AffiliationContext, account_id: int) -> Dict[str, Any]:
    """Account detail with clean ERP fields."""
    A, PA = Account, Account

    stmt = (
        select(
            A.id, A.code, A.name, A.account_type, A.report_type,
            A.is_group, A.debit_or_credit, A.enabled,
            A.company_id, A.parent_account_id,
            Company.name.label("company_name"),
            PA.name.label("parent_account_name"),
            PA.code.label("parent_account_code"),
        )
        .select_from(A)
        .join(Company, Company.id == A.company_id)
        .outerjoin(PA, PA.id == A.parent_account_id)
        .where(A.id == account_id)
    )
    hdr = _first_or_404(s, stmt, "Account")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    return {
        "basic_details": {
            "id": hdr["id"],
            "account_number": hdr["code"],
            "name": hdr["name"],
            "account_type": _enum_title(hdr["account_type"]),
            "report_type": _enum_title(hdr["report_type"]),
            "debit_or_credit": _enum_title(hdr["debit_or_credit"]),
            "is_group": bool(hdr["is_group"]),
            "enabled": bool(hdr["enabled"]),
            "parent_account": {
                "id": hdr["parent_account_id"],
                "code": hdr.get("parent_account_code"),
                "name": hdr.get("parent_account_name"),
            } if hdr["parent_account_id"] else None,
            "company_name": hdr["company_name"],
        }
    }
