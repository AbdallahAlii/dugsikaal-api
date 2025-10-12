# app/application_buying/query_builders/detail_builders.py
from __future__ import annotations
from typing import Dict, Any, Optional, Iterable, List, Tuple

from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound, Forbidden
from app.application_accounting.chart_of_accounts.models import Account
from app.application_accounting.chart_of_accounts.account_policies import ModeOfPayment
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Buying models
from app.application_buying.models import (
    PurchaseQuotation, PurchaseQuotationItem,
    PurchaseReceipt, PurchaseReceiptItem,
    PurchaseInvoice, PurchaseInvoiceItem,

)

# Lookups
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch
# If your Warehouse model lives elsewhere, update this import path:
from app.application_stock.stock_models import Warehouse  # <- adjust if needed
from app.application_nventory.inventory_models import Item, UnitOfMeasure  # for names

# -------------------------------------------------------------------
# Shared helpers
# -------------------------------------------------------------------

APP_TZ = timezone(timedelta(hours=3))  # Africa/Mogadishu (+03:00)

def _iso8601(dt: Optional[datetime]) -> Optional[str]:
    """
    Normalize datetimes to Africa/Mogadishu ISO-8601 strings.
    Example: '2025-09-15T10:00:00+03:00'
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    else:
        dt = dt.astimezone(APP_TZ)
    return dt.isoformat(timespec="seconds")

def _first_or_404(session: Session, stmt, label: str) -> dict:
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)

def _scope_predicates(model, ctx: AffiliationContext):
    """
    Return a SQLAlchemy boolean predicate limiting rows to the user's visibility:
      - company_id must match ctx.company_id
      - if ctx.branch_ids is non-empty -> restrict to those branches
      - if ctx.branch_ids empty (owner/super for that company) -> company-wide
    """
    co_id = getattr(ctx, "company_id", None)
    if co_id is None:
        # caller must always have a company in context for buying docs
        return (model.company_id == -1)  # impossible predicate
    base = (model.company_id == co_id)
    branch_ids = list(getattr(ctx, "branch_ids", []) or [])
    if branch_ids:
        return base & (model.branch_id.in_(branch_ids))
    return base

# -------------------------------------------------------------------
# Resolvers (code -> id), code is the ONLY identifier we expose
# They are scope-aware to avoid collisions across branches.
# -------------------------------------------------------------------

def resolve_receipt_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    PR = PurchaseReceipt
    pred = _scope_predicates(PR, ctx)
    stmt = select(PR.id, PR.company_id, PR.branch_id).where((PR.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Purchase Receipt not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)

def resolve_invoice_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    PI = PurchaseInvoice
    pred = _scope_predicates(PI, ctx)
    stmt = select(PI.id, PI.company_id, PI.branch_id).where((PI.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Purchase Invoice not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)

def resolve_quotation_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    PQ = PurchaseQuotation
    pred = _scope_predicates(PQ, ctx)
    stmt = select(PQ.id, PQ.company_id, PQ.branch_id).where((PQ.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Purchase Quotation not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)


# -------------------------------------------------------------------
# Loaders (id -> structured JSON)
# -------------------------------------------------------------------

def load_purchase_receipt(s: Session, ctx: AffiliationContext, receipt_id: int) -> Dict[str, Any]:
    PR, PRI = PurchaseReceipt, PurchaseReceiptItem

    # ---------- header ----------
    header_stmt = (
        select(
            PR.id, PR.code, PR.doc_status, PR.posting_date, PR.remarks,
            PR.company_id, PR.branch_id, PR.supplier_id, PR.warehouse_id, PR.total_amount,
            Party.name.label("supplier_name"),
            Branch.name.label("branch_name"),
            Warehouse.name.label("warehouse_name"),
        )
        .select_from(PR)
        .join(Party, Party.id == PR.supplier_id)
        .join(Branch, Branch.id == PR.branch_id)
        .outerjoin(Warehouse, Warehouse.id == PR.warehouse_id)
        .where(PR.id == receipt_id)
    )
    hdr = _first_or_404(s, header_stmt, "Purchase Receipt")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # ---------- items ----------
    items_stmt = (
        select(
            PRI.id, PRI.item_id, Item.name.label("item_name"),
            PRI.uom_id, UnitOfMeasure.name.label("uom_name"),
            PRI.received_qty, PRI.accepted_qty, PRI.unit_price, PRI.amount, PRI.remarks
        )
        .select_from(PRI)
        .join(Item, Item.id == PRI.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == PRI.uom_id)
        .where(PRI.receipt_id == receipt_id)
        .order_by(PRI.id.asc())
    )
    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]

    data = {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "doc_status": str(hdr["doc_status"]),
            "posting_date": _iso8601(hdr["posting_date"]),
            "company_id": hdr["company_id"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "supplier_id": hdr["supplier_id"],
            "supplier_name": hdr["supplier_name"],
            "warehouse_id": hdr["warehouse_id"],
            "warehouse_name": hdr["warehouse_name"],
            "remarks": hdr["remarks"],
        },
        "items": items,
        "financial_summary": {
            "total_amount": float(hdr["total_amount"]) if hdr["total_amount"] is not None else 0.0
        }
    }


    return data
def load_purchase_invoice(s: Session, ctx: AffiliationContext, invoice_id: int) -> Dict[str, Any]:
    PI, PII = PurchaseInvoice, PurchaseInvoiceItem

    # date-only formatter (YYYY-MM-DD) in APP_TZ
    def _date_only(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=APP_TZ)
        else:
            dt = dt.astimezone(APP_TZ)
        return dt.date().isoformat()

    # enum value extractor (returns "Submitted" instead of "DocStatusEnum.SUBMITTED")
    def _enum_value(x) -> str:
        return getattr(x, "value", x)

    # Aliases
    INV_WH = aliased(Warehouse)
    PR = aliased(PurchaseReceipt)
    RWH = aliased(Warehouse)
    RPTY = aliased(Party)
    AP = aliased(Account)
    CB = aliased(Account)
    MOP = aliased(ModeOfPayment)

    # ---------- header ----------
    header_stmt = (
        select(
            # core
            PI.id, PI.code, PI.doc_status, PI.update_stock,
            PI.posting_date, PI.dated, PI.due_date,
            PI.company_id, PI.branch_id, PI.supplier_id, PI.warehouse_id,
            PI.total_amount, PI.paid_amount, PI.outstanding_amount, PI.remarks,
            PI.is_return, PI.is_debit_note,
            PI.receipt_id,
            PI.payable_account_id,
            PI.mode_of_payment_id, PI.cash_bank_account_id,

            # names
            Party.name.label("supplier_name"),
            Branch.name.label("branch_name"),
            INV_WH.name.label("invoice_warehouse_name"),

            # receipt context
            PR.code.label("receipt_code"),
            RWH.id.label("receipt_warehouse_id"),
            RWH.name.label("receipt_warehouse_name"),
            RPTY.id.label("receipt_supplier_id"),
            RPTY.name.label("receipt_supplier_name"),

            # accounting names (ids are already on PI)
            AP.name.label("payable_account_name"),
            CB.name.label("cash_bank_account_name"),
            MOP.name.label("mode_of_payment_name"),
        )
        .select_from(PI)
        .join(Party, Party.id == PI.supplier_id)
        .join(Branch, Branch.id == PI.branch_id)
        .outerjoin(INV_WH, INV_WH.id == PI.warehouse_id)
        .outerjoin(PR, PR.id == PI.receipt_id)
        .outerjoin(RWH, RWH.id == PR.warehouse_id)
        .outerjoin(RPTY, RPTY.id == PR.supplier_id)
        .outerjoin(AP, AP.id == PI.payable_account_id)
        .outerjoin(CB, CB.id == PI.cash_bank_account_id)
        .outerjoin(MOP, MOP.id == PI.mode_of_payment_id)
        .where(PI.id == invoice_id)
    )
    hdr = _first_or_404(s, header_stmt, "Purchase Invoice")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # ---------- items ----------
    items_stmt = (
        select(
            PII.id, PII.item_id,
            Item.name.label("item_name"),
            PII.uom_id, UnitOfMeasure.name.label("uom_name"),
            PII.quantity, PII.rate, PII.amount,
            PII.receipt_item_id, PII.returned_qty, PII.remarks,
            PII.return_against_item_id
        )
        .select_from(PII)
        .join(Item, Item.id == PII.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == PII.uom_id)
        .where(PII.invoice_id == invoice_id)
        .order_by(PII.id.asc())
    )
    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]

    # absolute total qty (works for returns too)
    total_qty_abs = float(sum(abs(float(r.get("quantity") or 0)) for r in rows))

    data: Dict[str, Any] = {
        # ===== Basic Info =====
        "basic_details": {
            "id": hdr["id"],
            "doc_no": hdr["code"],
            "doc_status": _enum_value(hdr["doc_status"]),
            "is_return": bool(hdr["is_return"]),
            "is_debit_note": bool(hdr["is_debit_note"]),
            "posting_date": _date_only(hdr["posting_date"]),
            "dated": _date_only(hdr["dated"]),
            "due_date": _date_only(hdr["due_date"]),
        },

        # ===== Party & Branch =====
        "party_and_branch": {
            "company_id": hdr["company_id"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "supplier_id": hdr["supplier_id"],
            "supplier_name": hdr["supplier_name"],
            "receipt_supplier_id": hdr.get("receipt_supplier_id"),
            "receipt_supplier_name": hdr.get("receipt_supplier_name"),
        },

        # ===== Stock Info =====
        "stock_info": {
            "update_stock": bool(hdr["update_stock"]),
            "invoice_warehouse_id": hdr["warehouse_id"],
            "invoice_warehouse_name": hdr.get("invoice_warehouse_name"),
            "receipt_id": hdr["receipt_id"],
            "receipt_code": hdr.get("receipt_code"),
            "receipt_warehouse_id": hdr.get("receipt_warehouse_id"),
            "receipt_warehouse_name": hdr.get("receipt_warehouse_name"),
        },

        # ===== Payments (ids + names only) =====
        "payments": {
            "paid_amount": float(hdr["paid_amount"]) if hdr["paid_amount"] is not None else 0.0,
            "mode_of_payment": {
                "id": hdr.get("mode_of_payment_id"),
                "name": hdr.get("mode_of_payment_name"),
            },
            "cash_bank_account": {
                "id": hdr.get("cash_bank_account_id"),
                "name": hdr.get("cash_bank_account_name"),
            },
            "payable_account": {
                "id": hdr.get("payable_account_id"),
                "name": hdr.get("payable_account_name"),
            },
        },

        # ===== Financial Summary (DB field names) =====
        "financial_summary": {
            "total_qty": total_qty_abs,
            "total_amount": float(hdr["total_amount"]) if hdr["total_amount"] is not None else 0.0,
            "paid_amount": float(hdr["paid_amount"]) if hdr["paid_amount"] is not None else 0.0,
            "outstanding_amount": float(hdr["outstanding_amount"]) if hdr["outstanding_amount"] is not None else 0.0,
        },

        # ===== Items Grid =====
        "items": items,

        # ===== Meta =====
        "meta": {
            "remarks": hdr["remarks"],
        },
    }

    return data


def load_purchase_quotation(s: Session, ctx: AffiliationContext, quotation_id: int) -> Dict[str, Any]:
    PQ, PQI = PurchaseQuotation, PurchaseQuotationItem

    # ---------- header ----------
    header_stmt = (
        select(
            PQ.id, PQ.code, PQ.doc_status, PQ.posting_date, PQ.company_id, PQ.branch_id,
            PQ.supplier_id, PQ.remarks,
            Party.name.label("supplier_name"), Branch.name.label("branch_name")
        )
        .select_from(PQ)
        .join(Party, Party.id == PQ.supplier_id)
        .join(Branch, Branch.id == PQ.branch_id)
        .where(PQ.id == quotation_id)
    )
    hdr = _first_or_404(s, header_stmt, "Purchase Quotation")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # ---------- items ----------
    items_stmt = (
        select(
            PQI.id, PQI.item_id, Item.name.label("item_name"),
            PQI.uom_id, UnitOfMeasure.name.label("uom_name"),
            PQI.quantity, PQI.rate, PQI.amount
        )
        .select_from(PQI)
        .join(Item, Item.id == PQI.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == PQI.uom_id)
        .where(PQI.quotation_id == quotation_id)
        .order_by(PQI.id.asc())
    )
    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]

    # total = sum of amount (avoid None)
    total_amount = 0.0
    for r in rows:
        amt = r.get("amount")
        if amt is not None:
            total_amount += float(amt)

    data = {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "doc_status": str(hdr["doc_status"]),
            "posting_date": _iso8601(hdr["posting_date"]),
            "company_id": hdr["company_id"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
            "supplier_id": hdr["supplier_id"],
            "supplier_name": hdr["supplier_name"],
            "created_by_id": None,  # add if you want; not essential to return here
            "remarks": hdr["remarks"],
        },
        "items": items,
        "financial_summary": {
            "total_amount": total_amount
        }
    }
    return data


