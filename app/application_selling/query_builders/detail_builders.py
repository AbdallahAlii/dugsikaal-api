from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Models
from app.application_selling.models import (
    SalesQuotation, SalesQuotationItem,
    SalesDeliveryNote, SalesDeliveryNoteItem,
    SalesInvoice, SalesInvoiceItem,
)
from app.application_parties.parties_models import Party
from app.application_org.models.company import Branch
from app.application_stock.stock_models import Warehouse
from app.application_accounting.chart_of_accounts.models import Account
from app.application_accounting.chart_of_accounts.account_policies import ModeOfPayment

from app.application_nventory.inventory_models import Item, UnitOfMeasure


APP_TZ = timezone(timedelta(hours=3))  # Africa/Mogadishu (+03:00)


def _iso8601(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    else:
        dt = dt.astimezone(APP_TZ)
    return dt.isoformat(timespec="seconds")


def _date_only(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    else:
        dt = dt.astimezone(APP_TZ)
    return dt.date().isoformat()


def _enum_value(x) -> str:
    return getattr(x, "value", x)


def _first_or_404(s: Session, stmt, label: str) -> dict:
    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


def _scope_predicates(model, ctx: AffiliationContext):
    co_id = getattr(ctx, "company_id", None)
    if co_id is None:
        return (model.company_id == -1)
    base = (model.company_id == co_id)
    branch_ids = list(getattr(ctx, "branch_ids", []) or [])
    if branch_ids:
        return base & (model.branch_id.in_(branch_ids))
    return base


# ================
# Resolvers
# ================
def resolve_sales_invoice_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    SI = SalesInvoice
    pred = _scope_predicates(SI, ctx)
    stmt = select(SI.id, SI.company_id, SI.branch_id).where((SI.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Sales Invoice not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)


def resolve_delivery_note_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    SDN = SalesDeliveryNote
    pred = _scope_predicates(SDN, ctx)
    stmt = select(SDN.id, SDN.company_id, SDN.branch_id).where((SDN.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Delivery Note not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)


def resolve_sales_quotation_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    SQ = SalesQuotation
    pred = _scope_predicates(SQ, ctx)
    stmt = select(SQ.id, SQ.company_id, SQ.branch_id).where((SQ.code == code) & pred)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Sales Quotation not found for your scope.")
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=row.branch_id)
    return int(row.id)


# ================
# Loaders
# ================
def load_sales_invoice(s: Session, ctx: AffiliationContext, invoice_id: int) -> Dict[str, Any]:
    SI, SII = SalesInvoice, SalesInvoiceItem

    AP = aliased(Account)   # debit to
    CB = aliased(Account)   # cash/bank
    VAT = aliased(Account)  # vat
    MOP = aliased(ModeOfPayment)

    # ------- header (NO bogus warehouse join) -------
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
        .join(Party, Party.id == SI.customer_id)
        .join(Branch, Branch.id == SI.branch_id)
        .outerjoin(AP, AP.id == SI.debit_to_account_id)
        .outerjoin(CB, CB.id == SI.cash_bank_account_id)
        .outerjoin(VAT, VAT.id == SI.vat_account_id)
        .outerjoin(MOP, MOP.id == SI.mode_of_payment_id)
        .where(SI.id == invoice_id)
    )
    hdr = _first_or_404(s, header_stmt, "Sales Invoice")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    # ------- items -------
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
            "posting_date": _date_only(hdr["posting_date"]),
            "due_date": _date_only(hdr["due_date"]),
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
            },
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


def load_delivery_note(s: Session, ctx: AffiliationContext, dn_id: int) -> Dict[str, Any]:
    SDN, SDNI = SalesDeliveryNote, SalesDeliveryNoteItem

    header_stmt = (
        select(
            SDN.id, SDN.code, SDN.doc_status, SDN.posting_date, SDN.is_return,
            SDN.company_id, SDN.branch_id, SDN.customer_id,
            SDN.total_amount, SDN.remarks, SDN.return_against_id,
            Party.name.label("customer_name"),
            Branch.name.label("branch_name"),
        )
        .select_from(SDN)
        .join(Party, Party.id == SDN.customer_id)
        .join(Branch, Branch.id == SDN.branch_id)
        .where(SDN.id == dn_id)
    )
    hdr = _first_or_404(s, header_stmt, "Delivery Note")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

    items_stmt = (
        select(
            SDNI.id, SDNI.item_id, Item.name.label("item_name"),
            SDNI.uom_id, UnitOfMeasure.name.label("uom_name"),
            SDNI.warehouse_id, Warehouse.name.label("warehouse_name"),
            SDNI.delivered_qty, SDNI.unit_price, SDNI.amount,
            SDNI.return_against_item_id, SDNI.remarks,
        )
        .select_from(SDNI)
        .join(Item, Item.id == SDNI.item_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == SDNI.uom_id)
        .join(Warehouse, Warehouse.id == SDNI.warehouse_id)
        .where(SDNI.delivery_note_id == dn_id)
        .order_by(SDNI.id.asc())
    )
    rows = s.execute(items_stmt).mappings().all()
    items = [dict(r) for r in rows]
    total_qty_abs = float(sum(abs(float(r.get("delivered_qty") or 0)) for r in rows))

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "doc_status": _enum_value(hdr["doc_status"]),
            "posting_date": _date_only(hdr["posting_date"]),
            "is_return": bool(hdr["is_return"]),
            "return_against_id": hdr["return_against_id"],
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
            "total_qty": total_qty_abs,
            "total_amount": float(hdr["total_amount"]) if hdr["total_amount"] is not None else 0.0,
        },
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
        .join(Party, Party.id == SQ.customer_id)
        .join(Branch, Branch.id == SQ.branch_id)
        .where(SQ.id == sq_id)
    )
    hdr = _first_or_404(s, header_stmt, "Sales Quotation")
    ensure_scope_by_ids(context=ctx, target_company_id=hdr["company_id"], target_branch_id=hdr["branch_id"])

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
            "posting_date": _date_only(hdr["posting_date"]),
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
