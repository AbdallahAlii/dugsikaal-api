from __future__ import annotations

from typing import Dict, Any, Optional
from datetime import datetime, date

from sqlalchemy import select, and_, false, true as sql_true
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Time helpers (company timezone)
from app.common.timezone.service import get_company_timezone, ensure_aware

# Models
from app.application_selling.models import (
    SalesQuotation, SalesQuotationItem,

    SalesInvoice, SalesInvoiceItem,
)
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch
from app.application_stock.stock_models import Warehouse
from app.application_accounting.chart_of_accounts.models import Account
from app.application_accounting.chart_of_accounts.account_policies import ModeOfPayment
from app.application_nventory.inventory_models import Item, UnitOfMeasure


# ──────────────────────────────────────────────────────────────────────────────
# Small utilities
# ──────────────────────────────────────────────────────────────────────────────

def _is_system_admin(ctx: AffiliationContext) -> bool:
    if bool(getattr(ctx, "is_system_admin", False)):
        return True
    roles = getattr(ctx, "roles", None) or []
    return any((str(r) or "").lower() == "system admin" for r in roles)


def _company_predicate(model, ctx: AffiliationContext):
    """
    Company-only visibility rule:
      - Normal users: must have ctx.company_id and we filter by it.
      - System Admin: if ctx.company_id is None, allow all companies.
    """
    co_id = getattr(ctx, "company_id", None)
    if co_id is None:
        return sql_true() if _is_system_admin(ctx) else (model.company_id == -1)
    return model.company_id == co_id


def _first_or_404(s: Session, stmt, label: str) -> dict:
    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


def _enum_value(x) -> str:
    return getattr(x, "value", x)


def _date_out_iso(val: Optional[date | datetime], tz) -> Optional[str]:
    """
    Keep API date strings as YYYY-MM-DD (safe for HTML date inputs),
    but ensure correct company timezone if datetime is stored.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        local = ensure_aware(val, tz)
        return local.date().isoformat()
    return val.isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Resolvers (by code)
# NOTE: company-wide inside company (no branch restriction)
# ──────────────────────────────────────────────────────────────────────────────

def resolve_sales_invoice_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    SI = SalesInvoice
    pred = _company_predicate(SI, ctx)

    stmt = (
        select(SI.id, SI.company_id, SI.branch_id)
        .where(and_(SI.code == code, pred))
        .limit(1)
    )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Sales Invoice not found for your scope.")

    # Company-only enforcement (no branch restriction)
    ensure_scope_by_ids(context=ctx, target_company_id=row["company_id"], target_branch_id=None)
    return int(row["id"])





def resolve_sales_quotation_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    SQ = SalesQuotation
    pred = _company_predicate(SQ, ctx)

    stmt = (
        select(SQ.id, SQ.company_id, SQ.branch_id)
        .where(and_(SQ.code == code, pred))
        .limit(1)
    )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Sales Quotation not found for your scope.")

    ensure_scope_by_ids(context=ctx, target_company_id=row["company_id"], target_branch_id=None)
    return int(row["id"])


# ──────────────────────────────────────────────────────────────────────────────
# Loaders (detail)
# Performance notes:
#   • Header is 1 query, items is 1 query
#   • tenant-safe joins (company_id match) to prevent cross-company leakage
#   • scope enforcement is company-only (your requested ERP behavior)
# ──────────────────────────────────────────────────────────────────────────────

def load_sales_invoice(s: Session, ctx: AffiliationContext, invoice_id: int) -> Dict[str, Any]:
    SI, SII = SalesInvoice, SalesInvoiceItem

    AP = aliased(Account)   # debit to
    CB = aliased(Account)   # cash/bank
    VAT = aliased(Account)  # vat
    MOP = aliased(ModeOfPayment)

    header_stmt = (
        select(
            SI.id, SI.code, SI.doc_status, SI.update_stock,
            SI.posting_date, SI.due_date,
            SI.company_id, SI.branch_id, SI.customer_id,
            SI.total_amount, SI.paid_amount, SI.outstanding_amount, SI.remarks,
            SI.is_return,
            SI.debit_to_account_id, SI.cash_bank_account_id, SI.vat_account_id,
            SI.vat_rate, SI.vat_amount, SI.mode_of_payment_id,
            Party.name.label("customer_name"),
            Branch.name.label("branch_name"),
            AP.name.label("debit_to_account_name"),
            CB.name.label("cash_bank_account_name"),
            VAT.name.label("vat_account_name"),
            MOP.name.label("mode_of_payment_name"),
        )
        .select_from(SI)
        .join(Party, and_(Party.id == SI.customer_id, Party.company_id == SI.company_id))
        .join(Branch, and_(Branch.id == SI.branch_id, Branch.company_id == SI.company_id))
        .outerjoin(AP, and_(AP.id == SI.debit_to_account_id, AP.company_id == SI.company_id))
        .outerjoin(CB, and_(CB.id == SI.cash_bank_account_id, CB.company_id == SI.company_id))
        .outerjoin(VAT, and_(VAT.id == SI.vat_account_id, VAT.company_id == SI.company_id))
        .outerjoin(MOP, MOP.id == SI.mode_of_payment_id)
        .where(SI.id == invoice_id)
    )

    hdr = _first_or_404(s, header_stmt, "Sales Invoice")

    # Company-only scope (lets Branch A users view Branch B docs inside same company)
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    tz = get_company_timezone(s, int(hdr["company_id"]))

    items_stmt = (
        select(
            SII.id, SII.item_id, Item.name.label("item_name"),
            SII.uom_id, UnitOfMeasure.name.label("uom_name"),
            SII.quantity, SII.rate, SII.amount,
            SII.warehouse_id, Warehouse.name.label("warehouse_name"),
            SII.delivery_note_item_id,
            SII.income_account_id, SII.cost_center_id,
            SII.return_against_item_id,
            SII.remarks,
        )
        .select_from(SII)
        .join(Item, Item.id == SII.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == SII.uom_id)
        .outerjoin(Warehouse, Warehouse.id == SII.warehouse_id)
        .where(SII.invoice_id == invoice_id)
        .order_by(SII.id.asc())
    )

    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]
    total_qty_abs = float(sum(abs(float(r.get("quantity") or 0)) for r in rows))

    return {
        "basic_details": {
            "id": hdr["id"],
            "doc_no": hdr["code"],
            "doc_status": _enum_value(hdr["doc_status"]),
            "posting_date": _date_out_iso(hdr.get("posting_date"), tz),
            "due_date": _date_out_iso(hdr.get("due_date"), tz),
            "is_return": bool(hdr["is_return"]),
            "update_stock": bool(hdr["update_stock"]),
        },
        "party_and_branch": {
            "company_id": hdr["company_id"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "customer_id": hdr["customer_id"],
            "customer_name": hdr["customer_name"],
        },
        "payments_and_taxes": {
            "paid_amount": float(hdr["paid_amount"]) if hdr["paid_amount"] is not None else 0.0,
            "mode_of_payment": {"id": hdr.get("mode_of_payment_id"), "name": hdr.get("mode_of_payment_name")},
            "cash_bank_account": {"id": hdr.get("cash_bank_account_id"), "name": hdr.get("cash_bank_account_name")},
            "debit_to_account": {"id": hdr.get("debit_to_account_id"), "name": hdr.get("debit_to_account_name")},
            "vat": {
                "account": {"id": hdr.get("vat_account_id"), "name": hdr.get("vat_account_name")},
                "rate": float(hdr["vat_rate"]) if hdr.get("vat_rate") is not None else None,
                "amount": float(hdr["vat_amount"]) if hdr.get("vat_amount") is not None else 0.0,
            }, "payment_schedule": [],
        },

        "financial_summary": {
            "total_qty": total_qty_abs,
            "total_amount": float(hdr["total_amount"]) if hdr["total_amount"] is not None else 0.0,
            "paid_amount": float(hdr["paid_amount"]) if hdr["paid_amount"] is not None else 0.0,
            "outstanding_amount": float(hdr["outstanding_amount"]) if hdr["outstanding_amount"] is not None else 0.0,
        },
        "items": items,
        "meta": {"remarks": hdr["remarks"]},
    }



def load_sales_quotation(s: Session, ctx: AffiliationContext, sq_id: int) -> Dict[str, Any]:
    SQ, SQI = SalesQuotation, SalesQuotationItem

    header_stmt = (
        select(
            SQ.id, SQ.code, SQ.doc_status, SQ.posting_date,
            SQ.company_id, SQ.branch_id, SQ.customer_id, SQ.remarks,
            Party.name.label("customer_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(SQ)
        .join(Party, and_(Party.id == SQ.customer_id, Party.company_id == SQ.company_id))
        .join(Branch, and_(Branch.id == SQ.branch_id, Branch.company_id == SQ.company_id))
        .where(SQ.id == sq_id)
    )

    hdr = _first_or_404(s, header_stmt, "Sales Quotation")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=None)

    tz = get_company_timezone(s, int(hdr["company_id"]))

    items_stmt = (
        select(
            SQI.id, SQI.item_id, Item.name.label("item_name"),
            SQI.uom_id, UnitOfMeasure.name.label("uom_name"),
            SQI.quantity, SQI.rate, SQI.amount,
        )
        .select_from(SQI)
        .join(Item, Item.id == SQI.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == SQI.uom_id)
        .where(SQI.quotation_id == sq_id)
        .order_by(SQI.id.asc())
    )

    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]

    total_qty = float(sum(float(r.get("quantity") or 0) for r in rows))
    total_amount = float(sum(float(r.get("amount") or 0) for r in rows))

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "doc_status": _enum_value(hdr["doc_status"]),
            "posting_date": _date_out_iso(hdr.get("posting_date"), tz),
        },
        "party_and_branch": {
            "company_id": hdr["company_id"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "customer_id": hdr["customer_id"],
            "customer_name": hdr["customer_name"],
        },
        "items": items,
        "financial_summary": {
            "total_qty": total_qty,
            "total_amount": total_amount,
        },
        "meta": {"remarks": hdr["remarks"]},
    }
