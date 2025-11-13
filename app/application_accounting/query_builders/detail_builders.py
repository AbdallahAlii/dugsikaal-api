from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, date

from bidict._typing import DT
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType,PaymentEntry
from app.application_parties.parties_models import Party,PartyRoleEnum
from app.application_hr.models.hr import Employee,EmployeeAssignment
# Models
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment, ModeOfPaymentAccount
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear, CostCenter, Account, PartyTypeEnum
)
from app.application_org.models.company import Company, Branch
from app.application_stock.stock_models import DocumentType
from app.application_accounting.chart_of_accounts.finance_model import ExpenseType, ExpenseItem, Expense,PaymentItem


# ─────────────────────────── Date helpers (ERP-style, no time) ───────────────────────────
# Matches your display helper: if a datetime is passed, use its DATE part; format as mm/dd/YYYY.
_DISPLAY_FMT = "%m/%d/%Y"

def _format_date_out(d: date | datetime | None) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(_DISPLAY_FMT)


# ─────────────────────────── Common utils ───────────────────────────

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


# ─────────────────────────── Resolvers (by name/code) ───────────────────────────

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

def resolve_expense_type_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    ET = ExpenseType
    row = s.execute(select(ET.id, ET.company_id).where((ET.name == name) & (ET.company_id == ctx.company_id))).first()
    if not row:
        raise NotFound("Expense Type not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)
    return int(row.id)

def resolve_expense_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    E = Expense
    row = s.execute(
        select(E.id, E.company_id, E.branch_id)
        .where((E.code == code) & (E.company_id == ctx.company_id))
    ).first()
    if not row:
        raise NotFound("Expense not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
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
            "type": _enum_title(hdr["type"]),
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
            "year_start_date": _format_date_out(hdr["start_date"]),
            "year_end_date": _format_date_out(hdr["end_date"]),
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


def load_expense_type(s: Session, ctx: AffiliationContext, expense_type_id: int) -> Dict[str, Any]:
    ET, ACC = ExpenseType, Account

    stmt = (
        select(
            ET.id, ET.name, ET.description, ET.enabled,
            ET.default_account_id,
            ACC.code.label("default_account_code"),
            ACC.name.label("default_account_name"),
            ACC.enabled.label("default_account_enabled"),
            ET.company_id,
            Company.name.label("company_name"),
        )
        .select_from(ET)
        .join(Company, Company.id == ET.company_id)
        .outerjoin(ACC, ACC.id == ET.default_account_id)
        .where(ET.id == expense_type_id)
    )
    hdr = _first_or_404(s, stmt, "Expense Type")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    return {
        "basic_details": {
            "id": hdr["id"],
            "name": hdr["name"],
            "description": hdr["description"],
            "enabled": bool(hdr["enabled"]),
            "company_name": hdr["company_name"],
            "default_account": {
                "id": hdr["default_account_id"],
                "code": hdr.get("default_account_code"),
                "name": hdr.get("default_account_name"),
                "enabled": hdr.get("default_account_enabled"),
            } if hdr["default_account_id"] else None,
        }
    }


def load_expense(s: Session, ctx: AffiliationContext, expense_id: int) -> Dict[str, Any]:
    E = Expense

    # Header
    stmt = (
        select(
            E.id, E.code, E.doc_status, E.posting_date, E.total_amount,
            E.company_id, E.branch_id, E.cost_center_id, E.remarks,
            E.created_by_id, E.journal_entry_id,
            Company.name.label("company_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(E)
        .join(Company, Company.id == E.company_id)
        .join(Branch, Branch.id == E.branch_id)
        .where(E.id == expense_id)
    )
    hdr = _first_or_404(s, stmt, "Expense")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # Items
    EI, ET, ACC, ACC2, CC = ExpenseItem, ExpenseType, aliased(Account), aliased(Account), CostCenter
    items_stmt = (
        select(
            EI.id.label("id"),
            EI.description.label("description"),
            EI.amount.label("amount"),
            EI.cost_center_id.label("cost_center_id"),
            CC.name.label("cost_center_name"),

            EI.expense_type_id.label("expense_type_id"),
            ET.name.label("expense_type_name"),

            EI.account_id.label("account_id"),
            ACC.code.label("account_code"),
            ACC.name.label("account_name"),

            EI.paid_from_account_id.label("paid_from_account_id"),
            ACC2.code.label("paid_from_account_code"),
            ACC2.name.label("paid_from_account_name"),
        )
        .select_from(EI)
        .outerjoin(ET, ET.id == EI.expense_type_id)
        .join(ACC, ACC.id == EI.account_id)
        .join(ACC2, ACC2.id == EI.paid_from_account_id)
        .outerjoin(CC, CC.id == EI.cost_center_id)
        .where(EI.expense_id == expense_id)
        .order_by(EI.id.asc())
    )
    items = [dict(r) for r in s.execute(items_stmt).mappings().all()]

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "status": _enum_title(hdr["doc_status"]),
            "posting_date": _format_date_out(hdr["posting_date"]),
            "total_amount": hdr["total_amount"],
            "company_id": hdr["company_id"],
            "company_name": hdr["company_name"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "cost_center_id": hdr["cost_center_id"],
            "remarks": hdr["remarks"],
            "created_by_id": hdr["created_by_id"],
            "journal_entry_id": hdr["journal_entry_id"],
        },
        "items": items
    }


def resolve_payment_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    PE = PaymentEntry
    row = s.execute(
        select(PE.id, PE.company_id, PE.branch_id)
        .where((PE.code == code) & (PE.company_id == ctx.company_id))
    ).first()
    if not row:
        raise NotFound("Payment Entry not found.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)

# ─────────────────────────── Payment Items Function (FIXED) ───────────────────────────
def _get_payment_items(s: Session, payment_id: int) -> List[Dict[str, Any]]:
    """Get payment allocation items with proper invoice details"""
    PI = PaymentItem

    # Import the invoice models
    from app.application_selling.models import SalesInvoice
    from app.application_buying.models import PurchaseInvoice

    items = []

    # Get the payment items
    stmt = (
        select(
            PI.id,
            PI.source_doc_id,
            PI.allocated_amount,
        )
        .where(PI.payment_id == payment_id)
        .order_by(PI.id.asc())
    )

    payment_items = s.execute(stmt).mappings().all()

    for item in payment_items:
        source_doc_id = item["source_doc_id"]
        if not source_doc_id:
            continue

        # Try to find the source document and its details
        source_doc = None
        source_doctype = None
        source_code = None

        # Check if it's a Sales Invoice
        sales_inv = s.get(SalesInvoice, source_doc_id)
        if sales_inv:
            source_doc = sales_inv
            source_doctype = "SALES_INVOICE"
            source_code = sales_inv.code

        # If not Sales Invoice, check if it's a Purchase Invoice
        if not source_doc:
            purchase_inv = s.get(PurchaseInvoice, source_doc_id)
            if purchase_inv:
                source_doc = purchase_inv
                source_doctype = "PURCHASE_INVOICE"
                source_code = purchase_inv.code

        items.append({
            "id": item["id"],
            "source_doc_id": source_doc_id,
            "allocated_amount": float(item["allocated_amount"]),
            "source_doctype_code": source_code,
            "source_doctype_name": source_doctype,
        })

    return items
def load_payment(s: Session, ctx: AffiliationContext, payment_id: int) -> Dict[str, Any]:
    """Load payment entry details with all related information - FIXED references"""
    PE = PaymentEntry
    C = Company
    B = Branch
    MOP = ModeOfPayment
    ACC_FROM = aliased(Account)
    ACC_TO = aliased(Account)

    # Header with all relationships - single optimized query
    stmt = (
        select(
            # Basic Identity
            PE.id, PE.code, PE.payment_type, PE.doc_status,
            PE.posting_date, PE.paid_amount, PE.allocated_amount, PE.unallocated_amount,
            PE.reference_no, PE.reference_date, PE.remarks,

            # Company/Branch
            PE.company_id, PE.branch_id,
            C.name.label("company_name"),
            B.name.label("branch_name"),

            # Payment Method
            PE.mode_of_payment_id,
            MOP.name.label("mode_of_payment_name"),
            MOP.type.label("mode_of_payment_type"),

            # Accounts
            PE.paid_from_account_id,
            ACC_FROM.code.label("paid_from_account_code"),
            ACC_FROM.name.label("paid_from_account_name"),
            ACC_FROM.account_type.label("paid_from_account_type"),

            PE.paid_to_account_id,
            ACC_TO.code.label("paid_to_account_code"),
            ACC_TO.name.label("paid_to_account_name"),
            ACC_TO.account_type.label("paid_to_account_type"),

            # Party info
            PE.party_type, PE.party_id,

            # Created by
            PE.created_by_id,
            PE.journal_entry_id,
        )
        .select_from(PE)
        .join(C, C.id == PE.company_id)
        .join(B, B.id == PE.branch_id)
        .outerjoin(MOP, MOP.id == PE.mode_of_payment_id)
        .join(ACC_FROM, ACC_FROM.id == PE.paid_from_account_id)
        .join(ACC_TO, ACC_TO.id == PE.paid_to_account_id)
        .where(PE.id == payment_id)
    )

    hdr = _first_or_404(s, stmt, "Payment Entry")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # Get party details based on party_type
    party_info = _get_party_details(s, hdr["party_type"], hdr["party_id"])

    # Get allocation items (references) - using the FIXED function
    items = _get_payment_items(s, payment_id)

    # Get created by user info
    created_by_info = _get_created_by_info(s, hdr["created_by_id"])

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "payment_type": _enum_title(hdr["payment_type"]),
            "status": _enum_title(hdr["doc_status"]),
            "posting_date": _format_date_out(hdr["posting_date"]),
            "reference_no": hdr["reference_no"],
            "reference_date": _format_date_out(hdr["reference_date"]),
            "remarks": hdr["remarks"],
            "company_name": hdr["company_name"],
            "branch_name": hdr["branch_name"],
            "created_by": created_by_info,
            "journal_entry_id": hdr["journal_entry_id"],
        },
        "amounts": {
            "paid_amount": float(hdr["paid_amount"]),
            "allocated_amount": float(hdr["allocated_amount"]),
            "unallocated_amount": float(hdr["unallocated_amount"]),
        },
        "accounts": {
            "paid_from": {
                "id": hdr["paid_from_account_id"],
                "code": hdr["paid_from_account_code"],
                "name": hdr["paid_from_account_name"],
                "type": _enum_title(hdr["paid_from_account_type"]),
            },
            "paid_to": {
                "id": hdr["paid_to_account_id"],
                "code": hdr["paid_to_account_code"],
                "name": hdr["paid_to_account_name"],
                "type": _enum_title(hdr["paid_to_account_type"]),
            }
        },
        "payment_method": {
            "id": hdr["mode_of_payment_id"],
            "name": hdr["mode_of_payment_name"],
            "type": _enum_title(hdr["mode_of_payment_type"]) if hdr["mode_of_payment_type"] else None,
        } if hdr["mode_of_payment_id"] else None,
        "party": party_info,
        "references": items,
    }

def _get_party_details(s: Session, party_type: PartyTypeEnum, party_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Get party details based on party type"""
    if not party_type or not party_id:
        return None

    if party_type == PartyTypeEnum.CUSTOMER:
        stmt = select(Party.id, Party.name, Party.code, Party.phone).where(Party.id == party_id)
    elif party_type == PartyTypeEnum.SUPPLIER:
        stmt = select(Party.id, Party.name, Party.code, Party.phone).where(Party.id == party_id)
    elif party_type == PartyTypeEnum.EMPLOYEE:
        stmt = select(Employee.id, Employee.full_name.label("name"), Employee.code,
                      Employee.phone_number.label("phone")).where(Employee.id == party_id)
    else:
        return None

    row = s.execute(stmt).mappings().first()
    if not row:
        return None

    return {
        "type": _enum_title(party_type),
        "id": row["id"],
        "name": row["name"],
        "code": row["code"],
        "phone": row["phone"],
    }




def _get_created_by_info(s: Session, user_id: int) -> Dict[str, Any]:
    """Get basic created by user info - FIXED for your User model"""
    from app.auth.models.users import User
    U = User

    # Use only the fields that exist in your User model
    stmt = select(U.id, U.username).where(U.id == user_id)
    row = s.execute(stmt).mappings().first()

    if not row:
        return {"id": user_id, "name": "Unknown User"}

    return {
        "id": row["id"],
        "name": row["username"],  # Use username since you don't have full_name
        # Remove email field since it doesn't exist in your model
    }