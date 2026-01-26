
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import datetime, date

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_accounting.chart_of_accounts.finance_model import (
    ExpenseType,
    ExpenseItem,
    Expense,
    PaymentEntry,
    PaymentItem,
)
from app.application_parties.parties_models import Party
from app.application_hr.models.hr import Employee

# Models
from app.application_accounting.chart_of_accounts.account_policies import (
    ModeOfPayment,
    ModeOfPaymentAccount,
)
from app.application_accounting.chart_of_accounts.models import (
    FiscalYear,
    CostCenter,
    Account,
    PartyTypeEnum,
    JournalEntry,
    JournalEntryItem,
    PeriodClosingVoucher,
)
from app.application_org.models.company import Company, Branch

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
# --- Journal Entry resolvers ---


def resolve_journal_entry_by_code(
    s: Session, ctx: AffiliationContext, code: str
) -> int:
    JE = JournalEntry
    stmt = (
        select(JE.id, JE.company_id)
        .where((JE.code == code) & (JE.company_id == ctx.company_id))
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Journal Entry not found.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,  # company-wide for JE
    )
    return int(row.id)


def resolve_journal_entry_id_strict(
    s: Session, ctx: AffiliationContext, id_str: str
) -> int:
    try:
        je_id = int(id_str)
    except (TypeError, ValueError):
        raise NotFound("Journal Entry not found.")

    JE = JournalEntry
    stmt = (
        select(JE.id, JE.company_id)
        .where((JE.id == je_id) & (JE.company_id == ctx.company_id))
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Journal Entry not found.")

    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,
    )
    return int(row.id)


# --- Mode of Payment / Fiscal Year / Cost Center / Account / Expense / Payment ---


def resolve_mop_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    M = ModeOfPayment
    stmt = select(M.id, M.company_id).where(
        (M.name == name) & (M.company_id == ctx.company_id)
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Mode of Payment not found.")
    ensure_scope_by_ids(
        context=ctx, target_company_id=row.company_id, target_branch_id=None
    )
    return int(row.id)


def resolve_fiscal_year_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    FY = FiscalYear
    stmt = select(FY.id, FY.company_id).where(
        (FY.name == name) & (FY.company_id == ctx.company_id)
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Fiscal Year not found.")
    ensure_scope_by_ids(
        context=ctx, target_company_id=row.company_id, target_branch_id=None
    )
    return int(row.id)


def resolve_cost_center_by_name(
    s: Session, ctx: AffiliationContext, name: str
) -> int:
    CC = CostCenter
    stmt = select(CC.id, CC.company_id, CC.branch_id).where(
        (CC.name == name) & (CC.company_id == ctx.company_id)
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Cost Center not found.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id,
    )
    return int(row.id)


def resolve_account_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    A = Account
    row = s.execute(
        select(A.id, A.company_id).where(
            (A.name == name) & (A.company_id == ctx.company_id)
        )
    ).first()
    if not row:
        raise NotFound("Account not found.")
    ensure_scope_by_ids(
        context=ctx, target_company_id=row.company_id, target_branch_id=None
    )
    return int(row.id)


def resolve_expense_type_by_name(
    s: Session, ctx: AffiliationContext, name: str
) -> int:
    ET = ExpenseType
    row = s.execute(
        select(ET.id, ET.company_id).where(
            (ET.name == name) & (ET.company_id == ctx.company_id)
        )
    ).first()
    if not row:
        raise NotFound("Expense Type not found.")
    ensure_scope_by_ids(
        context=ctx, target_company_id=row.company_id, target_branch_id=None
    )
    return int(row.id)


def resolve_expense_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    E = Expense
    row = s.execute(
        select(E.id, E.company_id, E.branch_id).where(
            (E.code == code) & (E.company_id == ctx.company_id)
        )
    ).first()
    if not row:
        raise NotFound("Expense not found.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id,
    )
    return int(row.id)


def resolve_payment_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    PE = PaymentEntry
    row = s.execute(
        select(PE.id, PE.company_id, PE.branch_id).where(
            (PE.code == code) & (PE.company_id == ctx.company_id)
        )
    ).first()
    if not row:
        raise NotFound("Payment Entry not found.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id,
    )
    return int(row.id)


# --- Period Closing Voucher resolvers ---


def resolve_pcv_by_code(
    s: Session, ctx: AffiliationContext, code: str
) -> int:
    PCV = PeriodClosingVoucher
    stmt = (
        select(PCV.id, PCV.company_id)
        .where((PCV.code == code) & (PCV.company_id == ctx.company_id))
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Period Closing Voucher not found.")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,  # company-level doc
    )
    return int(row.id)


def resolve_pcv_id_strict(
    s: Session, ctx: AffiliationContext, id_str: str
) -> int:
    try:
        pcv_id = int(id_str)
    except (TypeError, ValueError):
        raise NotFound("Period Closing Voucher not found.")

    PCV = PeriodClosingVoucher
    stmt = (
        select(PCV.id, PCV.company_id)
        .where((PCV.id == pcv_id) & (PCV.company_id == ctx.company_id))
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Period Closing Voucher not found.")

    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,
    )
    return int(row.id)


# ─────────────────────────── Loaders (detail JSON) ───────────────────────────
# -------- Mode of Payment --------


def load_mode_of_payment(
    s: Session, ctx: AffiliationContext, mop_id: int
) -> Dict[str, Any]:
    """Return MoP detail WITHOUT access_control block; friendly enum titles."""
    M, MA, ACC = ModeOfPayment, ModeOfPaymentAccount, Account

    # Header
    header_stmt = (
        select(
            M.id,
            M.name,
            M.type,
            M.enabled,
            M.company_id,
            Company.name.label("company_name"),
        )
        .select_from(M)
        .join(Company, Company.id == M.company_id)
        .where(M.id == mop_id)
    )
    hdr = _first_or_404(s, header_stmt, "Mode of Payment")
    ensure_scope_by_ids(
        context=ctx, target_company_id=hdr["company_id"], target_branch_id=None
    )

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
        "accounts": accounts,
    }


# -------- Fiscal Year --------


def load_fiscal_year(
    s: Session, ctx: AffiliationContext, fiscal_year_id: int
) -> Dict[str, Any]:
    FY = FiscalYear

    stmt = (
        select(
            FY.id,
            FY.name,
            FY.status,
            FY.start_date,
            FY.end_date,
            FY.is_short_year,
            FY.company_id,
            Company.name.label("company_name"),
        )
        .select_from(FY)
        .join(Company, Company.id == FY.company_id)
        .where(FY.id == fiscal_year_id)
    )
    hdr = _first_or_404(s, stmt, "Fiscal Year")
    ensure_scope_by_ids(
        context=ctx, target_company_id=hdr["company_id"], target_branch_id=None
    )

    return {
        "basic_details": {
            "id": hdr["id"],
            "name": hdr["name"],
            "status": _enum_title(hdr["status"]),  # "Open", "Closed", etc.
            "start_date": _format_date_out(hdr["start_date"]),
            "end_date": _format_date_out(hdr["end_date"]),
            "is_short_year": bool(hdr["is_short_year"]),
            "company_name": hdr["company_name"],
        }
    }



# -------- Cost Center --------


def load_cost_center(
    s: Session, ctx: AffiliationContext, cost_center_id: int
) -> Dict[str, Any]:
    CC = CostCenter

    stmt = (
        select(
            CC.id,
            CC.name,
            CC.enabled,
            CC.company_id,
            CC.branch_id,
            Company.name.label("company_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(CC)
        .join(Company, Company.id == CC.company_id)
        .join(Branch, Branch.id == CC.branch_id)
        .where(CC.id == cost_center_id)
    )
    hdr = _first_or_404(s, stmt, "Cost Center")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=hdr["branch_id"],
    )

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


# -------- Account --------


def load_account(
    s: Session, ctx: AffiliationContext, account_id: int
) -> Dict[str, Any]:
    """Account detail with clean ERP fields."""
    A, PA = Account, Account

    stmt = (
        select(
            A.id,
            A.code,
            A.name,
            A.account_type,
            A.report_type,
            A.is_group,
            A.debit_or_credit,
            A.enabled,
            A.company_id,
            A.parent_account_id,
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
    ensure_scope_by_ids(
        context=ctx, target_company_id=hdr["company_id"], target_branch_id=None
    )

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
            }
            if hdr["parent_account_id"]
            else None,
            "company_name": hdr["company_name"],
        }
    }


# -------- Expense Type --------


def load_expense_type(
    s: Session, ctx: AffiliationContext, expense_type_id: int
) -> Dict[str, Any]:
    ET, ACC = ExpenseType, Account

    stmt = (
        select(
            ET.id,
            ET.name,
            ET.description,
            ET.enabled,
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
    ensure_scope_by_ids(
        context=ctx, target_company_id=hdr["company_id"], target_branch_id=None
    )

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
            }
            if hdr["default_account_id"]
            else None,
        }
    }


# -------- Expense --------


def load_expense(
    s: Session, ctx: AffiliationContext, expense_id: int | str
) -> Dict[str, Any]:
    """
    Load Expense detail.

    `expense_id` can be:
      - internal numeric id
      - or business code (e.g. "EXP-2025-00001")
    """
    # Resolve id vs code in a backward-compatible way
    if isinstance(expense_id, int):
        resolved_id = expense_id
    else:
        ident_str = str(expense_id)
        try:
            resolved_id = int(ident_str)
        except (TypeError, ValueError):
            # Fallback: resolve by business code
            resolved_id = resolve_expense_by_code(s, ctx, ident_str)

    E = Expense

    # Header
    stmt = (
        select(
            E.id,
            E.code,
            E.doc_status,
            E.posting_date,
            E.total_amount,
            E.company_id,
            E.branch_id,
            E.cost_center_id,
            E.remarks,
            E.created_by_id,
            E.journal_entry_id,
            Company.name.label("company_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(E)
        .join(Company, Company.id == E.company_id)
        .join(Branch, Branch.id == E.branch_id)
        .where(E.id == resolved_id)
    )
    hdr = _first_or_404(s, stmt, "Expense")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=hdr["branch_id"],
    )

    # Items
    EI, ET, ACC, ACC2, CC = (
        ExpenseItem,
        ExpenseType,
        aliased(Account),
        aliased(Account),
        CostCenter,
    )
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
        .where(EI.expense_id == resolved_id)
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
        "items": items,
    }


# ─────────────────────────── Payment loaders ───────────────────────────
def _get_payment_items(s: Session, payment_id: int) -> List[Dict[str, Any]]:
    """Get payment allocation items with proper invoice details"""
    PI = PaymentItem

    # Import the invoice models
    from app.application_selling.models import SalesInvoice
    from app.application_buying.models import PurchaseInvoice

    items: List[Dict[str, Any]] = []

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

        source_doctype = None
        source_code = None

        # Try Sales Invoice
        sales_inv = s.get(SalesInvoice, source_doc_id)
        if sales_inv:
            source_doctype = "SALES_INVOICE"
            source_code = sales_inv.code
        else:
            # Try Purchase Invoice
            purchase_inv = s.get(PurchaseInvoice, source_doc_id)
            if purchase_inv:
                source_doctype = "PURCHASE_INVOICE"
                source_code = purchase_inv.code

        items.append(
            {
                "id": item["id"],
                "source_doc_id": source_doc_id,
                "allocated_amount": float(item["allocated_amount"]),
                "source_doctype_code": source_code,
                "source_doctype_name": source_doctype,
            }
        )

    return items


def load_payment(
    s: Session, ctx: AffiliationContext, payment_id: int | str
) -> Dict[str, Any]:
    """
    Load payment entry details with all related information.

    `payment_id` can be:
      - internal numeric id
      - or business code (e.g. "PAY-2025-00024")
    """
    # Resolve id vs code in a backward-compatible way
    if isinstance(payment_id, int):
        resolved_id = payment_id
    else:
        ident_str = str(payment_id)
        try:
            resolved_id = int(ident_str)
        except (TypeError, ValueError):
            # Fallback: resolve by business code
            resolved_id = resolve_payment_by_code(s, ctx, ident_str)

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
            PE.id,
            PE.code,
            PE.payment_type,
            PE.doc_status,
            PE.posting_date,
            PE.paid_amount,
            PE.allocated_amount,
            PE.unallocated_amount,
            PE.reference_no,
            PE.reference_date,
            PE.remarks,
            # Company/Branch
            PE.company_id,
            PE.branch_id,
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
            PE.party_type,
            PE.party_id,
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
        .where(PE.id == resolved_id)
    )

    hdr = _first_or_404(s, stmt, "Payment Entry")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=hdr["branch_id"],
    )

    # Party details
    party_info = _get_party_details(s, hdr["party_type"], hdr["party_id"])

    # Allocation items
    items = _get_payment_items(s, resolved_id)

    # Created-by info
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
            },
        },
        "payment_method": {
            "id": hdr["mode_of_payment_id"],
            "name": hdr["mode_of_payment_name"],
            "type": _enum_title(hdr["mode_of_payment_type"])
            if hdr["mode_of_payment_type"]
            else None,
        }
        if hdr["mode_of_payment_id"]
        else None,
        "party": party_info,
        "references": items,
    }


def _get_party_details(
    s: Session, party_type: PartyTypeEnum, party_id: Optional[int]
) -> Optional[Dict[str, Any]]:
    """Get party details based on party type"""
    if not party_type or not party_id:
        return None

    if party_type == PartyTypeEnum.CUSTOMER:
        stmt = select(
            Party.id, Party.name, Party.code, Party.phone
        ).where(Party.id == party_id)
    elif party_type == PartyTypeEnum.SUPPLIER:
        stmt = select(
            Party.id, Party.name, Party.code, Party.phone
        ).where(Party.id == party_id)
    elif party_type == PartyTypeEnum.EMPLOYEE:
        stmt = select(
            Employee.id,
            Employee.full_name.label("name"),
            Employee.code,
            Employee.phone_number.label("phone"),
        ).where(Employee.id == party_id)
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
    """Get basic created by user info - using your User model"""
    from app.auth.models.users import User

    U = User
    stmt = select(U.id, U.username).where(U.id == user_id)
    row = s.execute(stmt).mappings().first()

    if not row:
        return {"id": user_id, "name": "Unknown User"}

    return {
        "id": row["id"],
        "name": row["username"],
    }


# -------- Journal Entry --------
def load_journal_entry(
    s: Session, ctx: AffiliationContext, je_id: int | str
) -> Dict[str, Any]:
    """
    ERP-style Journal Entry detail.

    `je_id` can be:
      - internal numeric id
      - or business code (e.g. "JV-2025-00001")

    Sections:
      - basic_details
      - company_context
      - accounting_entries (lines)
        * each line now has:
            - party_type: "Customer" / "Supplier" / "Employee" (or None)
            - party: { id, name } (or None)
    """
    # Resolve id vs code
    if isinstance(je_id, int):
        resolved_id = je_id
    else:
        ident_str = str(je_id)
        try:
            resolved_id = int(ident_str)
        except (TypeError, ValueError):
            resolved_id = resolve_journal_entry_by_code(s, ctx, ident_str)

    JE = JournalEntry
    JLI = JournalEntryItem
    ACC = Account
    CC = CostCenter
    C = Company
    B = Branch

    # ----- Header -----
    header_stmt = (
        select(
            JE.id,
            JE.code,
            JE.doc_status,
            JE.entry_type,
            JE.posting_date,
            JE.total_debit,
            JE.total_credit,
            JE.company_id,
            JE.branch_id,
            C.name.label("company_name"),
            B.name.label("branch_name"),
            JE.remarks,
        )
        .select_from(JE)
        .join(C, C.id == JE.company_id)
        .join(B, B.id == JE.branch_id)
        .where(JE.id == resolved_id)
    )
    hdr = _first_or_404(s, header_stmt, "Journal Entry")

    # Company-wide scope (no branch restriction for JE)
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=None,
    )

    # ----- Lines (Accounting Entries) -----
    stmt_items = (
        select(
            JLI.id.label("id"),
            JLI.account_id.label("account_id"),
            ACC.code.label("account_code"),
            ACC.name.label("account_name"),
            JLI.cost_center_id.label("cost_center_id"),
            CC.name.label("cost_center_name"),
            JLI.party_type.label("party_type"),
            JLI.party_id.label("party_id"),
            JLI.debit.label("debit"),
            JLI.credit.label("credit"),
            JLI.remarks.label("remarks"),
        )
        .select_from(JLI)
        .join(ACC, ACC.id == JLI.account_id)
        .outerjoin(CC, CC.id == JLI.cost_center_id)
        .where(JLI.journal_entry_id == resolved_id)
        .order_by(JLI.id.asc())
    )

    raw_items = s.execute(stmt_items).mappings().all()

    accounting_entries: List[Dict[str, Any]] = []
    for r in raw_items:
        r = dict(r)
        debit = Decimal(str(r["debit"] or 0))
        credit = Decimal(str(r["credit"] or 0))

        party_type_label: Optional[str] = None
        party_min: Optional[Dict[str, Any]] = None

        if r["party_type"] and r["party_id"]:
            full_party = _get_party_details(s, r["party_type"], r["party_id"])
            if full_party:
                party_type_label = full_party.get("type")
                party_min = {
                    "id": full_party.get("id"),
                    "name": full_party.get("name"),
                }

        accounting_entries.append(
            {
                "id": r["id"],
                "account": {
                    "id": r["account_id"],
                    "code": r["account_code"],
                    "name": r["account_name"],
                },
                "cost_center": {
                    "id": r["cost_center_id"],
                    "name": r["cost_center_name"],
                }
                if r["cost_center_id"]
                else None,
                "party_type": party_type_label,
                "party": party_min,
                "debit": float(debit),
                "credit": float(credit),
                "remarks": r["remarks"],
            }
        )

    total_debit = Decimal(str(hdr["total_debit"] or 0))
    total_credit = Decimal(str(hdr["total_credit"] or 0))

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "status": _enum_title(hdr["doc_status"]),
            "entry_type": _enum_title(hdr["entry_type"]),
            "posting_date": _format_date_out(hdr["posting_date"]),
            "total_debit": float(total_debit),
            "total_credit": float(total_credit),
            "difference": float(total_debit - total_credit),
            "remarks": hdr["remarks"],
        },
        "company_context": {
            "company_id": hdr["company_id"],
            "company_name": hdr["company_name"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
        },
        "accounting_entries": accounting_entries,
    }


# -------- Period Closing Voucher --------
def load_period_closing_voucher(
    s: Session, ctx: AffiliationContext, pcv_id: int | str
) -> Dict[str, Any]:
    """
    ERP-style Period Closing Voucher detail.

    `pcv_id` can be:
      - internal numeric id
      - or business code (e.g. "PCV-2025-00001")

    Sections:
      - basic_details
      - company_context
      - closing_fiscal_year
      - closing_account
      - submission
      - generated_journal_entry
    """
    # Resolve id vs code
    if isinstance(pcv_id, int):
        resolved_id = pcv_id
    else:
        ident_str = str(pcv_id)
        try:
            resolved_id = int(ident_str)
        except (TypeError, ValueError):
            resolved_id = resolve_pcv_by_code(s, ctx, ident_str)

    PCV = PeriodClosingVoucher
    FY = FiscalYear
    ACC = Account
    C = Company
    JE = JournalEntry

    header_stmt = (
        select(
            PCV.id,
            PCV.code,
            PCV.doc_status,
            PCV.posting_date,
            PCV.remarks,
            PCV.auto_prepared,
            PCV.total_profit_loss,
            PCV.company_id,
            PCV.closing_fiscal_year_id,
            PCV.closing_account_head_id,
            PCV.generated_journal_entry_id,
            PCV.submitted_by_id,
            PCV.submitted_at,
            C.name.label("company_name"),
            FY.name.label("fy_name"),
            FY.start_date.label("fy_start_date"),
            FY.end_date.label("fy_end_date"),
            FY.status.label("fy_status"),
            ACC.code.label("closing_account_code"),
            ACC.name.label("closing_account_name"),
            JE.code.label("je_code"),
        )
        .select_from(PCV)
        .join(C, C.id == PCV.company_id)
        .join(FY, FY.id == PCV.closing_fiscal_year_id)
        .join(ACC, ACC.id == PCV.closing_account_head_id)
        .outerjoin(JE, JE.id == PCV.generated_journal_entry_id)
        .where(PCV.id == resolved_id)
    )

    hdr = _first_or_404(s, header_stmt, "Period Closing Voucher")
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=None,  # company-level doc
    )

    pl = Decimal(str(hdr["total_profit_loss"] or 0))
    if pl > 0:
        pl_label = "Profit"
    elif pl < 0:
        pl_label = "Loss"
    else:
        pl_label = "Zero"

    submitted_by_info = (
        _get_created_by_info(s, hdr["submitted_by_id"])
        if hdr["submitted_by_id"]
        else None
    )

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "status": _enum_title(hdr["doc_status"]),
            "posting_date": _format_date_out(hdr["posting_date"]),
            "remarks": hdr["remarks"],
            "auto_prepared": bool(hdr["auto_prepared"]),
            "total_profit_loss": float(pl),
            "profit_or_loss": pl_label,
        },
        "company_context": {
            "company_id": hdr["company_id"],
            "company_name": hdr["company_name"],
        },
        "closing_fiscal_year": {
            "id": hdr["closing_fiscal_year_id"],
            "name": hdr["fy_name"],
            "status": _enum_title(hdr["fy_status"]),
            "year_start_date": _format_date_out(hdr["fy_start_date"]),
            "year_end_date": _format_date_out(hdr["fy_end_date"]),
        },
        "closing_account": {
            "id": hdr["closing_account_head_id"],
            "code": hdr["closing_account_code"],
            "name": hdr["closing_account_name"],
        },
        "submission": {
            "submitted_at": _format_date_out(hdr["submitted_at"])
            if hdr["submitted_at"]
            else None,
            "submitted_by": submitted_by_info,
        },
        "generated_journal_entry": {
            "id": hdr["generated_journal_entry_id"],
            "code": hdr["je_code"],
        }
        if hdr["generated_journal_entry_id"]
        else None,
    }
