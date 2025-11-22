from __future__ import annotations
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, date

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_stock.stock_models import StockEntry, StockEntryItem, Warehouse
from app.application_nventory.inventory_models import Item, UnitOfMeasure
from app.application_accounting.chart_of_accounts.models import Account
from app.application_org.models.company import Company, Branch


_DISPLAY_FMT = "%m/%d/%Y"


def _format_date_out(d: date | datetime | None) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime(_DISPLAY_FMT)


def _format_decimal(v: Optional[Decimal]) -> Optional[float]:
    if v is None:
        return None
    return float(v)


def _enum_value(x) -> str:
    return getattr(x, "value", str(x))


def _first_or_404(session: Session, stmt, label: str) -> Dict[str, Any]:
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


# ─────────────────────────── Resolvers ───────────────────────────

def resolve_stock_entry_by_code(
    s: Session, ctx: AffiliationContext, code: str
) -> int:
    SE = StockEntry
    stmt = (
        select(SE.id, SE.company_id)
        .where((SE.code == code) & (SE.company_id == ctx.company_id))
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Stock Entry not found.")

    # Company-wide scope (no branch restriction)
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,
    )
    return int(row.id)


def resolve_stock_entry_id_strict(
    s: Session, ctx: AffiliationContext, id_str: str
) -> int:
    try:
        se_id = int(id_str)
    except (TypeError, ValueError):
        raise NotFound("Stock Entry not found.")

    SE = StockEntry
    stmt = select(SE.id, SE.company_id).where(
        (SE.id == se_id) & (SE.company_id == ctx.company_id)
    )
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Stock Entry not found.")

    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=None,
    )
    return int(row.id)


# ─────────────────────────── Loader ───────────────────────────

def load_stock_entry_detail(
    s: Session, ctx: AffiliationContext, se_id: int
) -> Dict[str, Any]:
    """
    ERP-style Stock Entry detail JSON.

    Sections:
      - basic_details
      - company_context
      - accounting
      - items
    """
    SE = StockEntry
    SEI = StockEntryItem
    W = Warehouse
    I = Item
    UOM = UnitOfMeasure
    ACC = Account

    # ----- Header -----
    diff_acc = aliased(ACC)

    header_stmt = (
        select(
            SE.id,
            SE.code,
            SE.doc_status,
            SE.stock_entry_type,
            SE.posting_date,
            SE.company_id,
            SE.branch_id,
            SE.difference_account_id,
            Company.name.label("company_name"),
            Branch.name.label("branch_name"),
            diff_acc.code.label("difference_account_code"),
            diff_acc.name.label("difference_account_name"),
        )
        .select_from(SE)
        .join(Company, Company.id == SE.company_id)
        .join(Branch, Branch.id == SE.branch_id)
        .outerjoin(diff_acc, diff_acc.id == SE.difference_account_id)
        .where(SE.id == se_id)
    )

    hdr = _first_or_404(s, header_stmt, "Stock Entry")

    # Company-level scope (no branch restriction for SE)
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=hdr["company_id"],
        target_branch_id=None,
    )

    # ----- Items grid -----
    W_FROM = aliased(W)
    W_TO = aliased(W)

    items_stmt = (
        select(
            SEI.id.label("id"),

            SEI.item_id.label("item_id"),
            I.name.label("item_name"),

            SEI.source_warehouse_id.label("source_warehouse_id"),
            W_FROM.name.label("source_warehouse_name"),

            SEI.target_warehouse_id.label("target_warehouse_id"),
            W_TO.name.label("target_warehouse_name"),

            SEI.uom_id.label("uom_id"),
            UOM.name.label("uom_name"),

            SEI.quantity.label("quantity"),
            SEI.rate.label("rate"),
            SEI.amount.label("amount"),
        )
        .select_from(SEI)
        .join(I, I.id == SEI.item_id)
        .outerjoin(W_FROM, W_FROM.id == SEI.source_warehouse_id)
        .outerjoin(W_TO, W_TO.id == SEI.target_warehouse_id)
        .join(UOM, UOM.id == SEI.uom_id)
        .where(SEI.stock_entry_id == se_id)
        .order_by(SEI.id.asc())
    )

    rows = s.execute(items_stmt).mappings().all()

    items = []
    for r in rows:
        r = dict(r)
        items.append(
            {
                "id": r["id"],
                "item": {
                    "id": r["item_id"],
                    "name": r["item_name"],
                },
                "source_warehouse": {
                    "id": r["source_warehouse_id"],
                    "name": r["source_warehouse_name"],
                }
                if r["source_warehouse_id"]
                else None,
                "target_warehouse": {
                    "id": r["target_warehouse_id"],
                    "name": r["target_warehouse_name"],
                }
                if r["target_warehouse_id"]
                else None,
                "uom": {
                    "id": r["uom_id"],
                    "name": r["uom_name"],
                },
                "qty": _format_decimal(r["quantity"]),
                "rate": _format_decimal(r["rate"]),
                "amount": _format_decimal(r["amount"]),
            }
        )

    return {
        "basic_details": {
            "id": hdr["id"],
            "code": hdr["code"],
            "status": _enum_value(hdr["doc_status"]),
            "stock_entry_type": _enum_value(hdr["stock_entry_type"]),
            "posting_date": _format_date_out(hdr["posting_date"]),
        },
        "company_context": {
            "company_id": hdr["company_id"],
            "company_name": hdr["company_name"],
            "branch_id": hdr["branch_id"],
            "branch_name": hdr["branch_name"],
        },
        "accounting": {
            "difference_account": {
                "id": hdr["difference_account_id"],
                "code": hdr["difference_account_code"],
                "name": hdr["difference_account_name"],
            }
            if hdr["difference_account_id"]
            else None
        },
        "items": items,
    }
