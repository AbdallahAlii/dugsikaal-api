from __future__ import annotations

from typing import Optional

from sqlalchemy import select, false, case
from sqlalchemy.orm import Session

from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids


def build_warehouses_query(session: Session, context: AffiliationContext):
    """
    Company-wide warehouses list.

    RULE (your requirement):
      - Any user within the company can see ALL warehouses in that company
        (global + all branches).
      - No cross-company leakage.

    This is ERP-style: warehouses are masters for the whole company.
    Branch isolation is for transactions, not master visibility.
    """

    co_id: Optional[int] = getattr(context, "company_id", None)
    if co_id is None:
        return select(Warehouse.id).where(false())

    # Enforce company scope (system-admin bypass is handled inside)
    ensure_scope_by_ids(context=context, target_company_id=co_id, target_branch_id=None)

    W = Warehouse
    B = Branch

    location_display = case(
        (W.branch_id.is_(None), "Global"),
        else_=B.name,
    ).label("location")

    q = (
        select(
            W.id.label("id"),
            W.code.label("code"),
            W.name.label("warehouse_name"),
            W.status.label("status"),
            location_display,
            W.is_group.label("is_group"),
            W.branch_id.label("branch_id"),
            W.parent_warehouse_id.label("parent_warehouse_id"),
        )
        .select_from(W)
        .outerjoin(B, B.id == W.branch_id)
        .where(W.company_id == co_id)
        .order_by(W.is_group.desc(), location_display.asc(), W.name.asc())
    )

    return q
