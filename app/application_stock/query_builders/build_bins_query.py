# app/application_stock/query_builders/build_bins_query.py
from __future__ import annotations
from typing import Optional

from sqlalchemy import select, or_, false
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_stock.stock_models import Bin
from app.application_nventory.inventory_models import Item
from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch, Company

def build_bins_query(session: Session, context: AffiliationContext):
    """
    Company/branch-scoped list of Bins with ERP-style columns.
    Shows: code, warehouse_name, item_name, actual_qty, valuation_rate.
    """
    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(Bin.id).where(false())

    b = Bin
    w = Warehouse
    i = Item
    br = Branch
    co = Company

    q = (
        select(
            b.id.label("id"),
            b.code.label("code"),
            w.name.label("warehouse_name"),
            i.name.label("item_name"),
            b.actual_qty.label("actual_qty"),
            b.valuation_rate.label("valuation_rate"),
        )
        .select_from(b)
        .join(w, w.id == b.warehouse_id)
        .join(co, co.id == b.company_id)
        .outerjoin(br, br.id == w.branch_id)
        .join(i, i.id == b.item_id)
        .where(b.company_id == co_id)
    )

    # Branch scoping (mirror your Warehouse list logic)
    if not getattr(context, "is_system_admin", False):
        roles = getattr(context, "roles", []) or []
        has_company_wide_access = any(role in ["Owner", "Super Admin"] for role in roles)

        if not has_company_wide_access:
            branch_ids = list(getattr(context, "branch_ids", []) or [])
            if branch_ids:
                q = q.where(
                    or_(
                        w.branch_id.in_(branch_ids),
                        w.branch_id.is_(None)  # Global warehouses
                    )
                )
            else:
                q = q.where(w.branch_id.is_(None))

    return q
