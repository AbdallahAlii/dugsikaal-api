# app/application_stock/query_builders/bin_detail_builders.py
from __future__ import annotations
from typing import Dict, Any, Optional

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch, Company
from app.application_stock.stock_models import Bin
from app.application_nventory.inventory_models import Item

# ---------------- utils ----------------
def _f(x: Optional[Decimal]) -> float:
    if x is None:
        return 0.0
    try:
        return float(x)
    except Exception:
        return float(str(x))

def _require_non_empty(v: str, label: str) -> str:
    vv = (v or "").strip()
    if not vv:
        raise BadRequest(f"{label} required.")
    return vv

# Reuse a strict id resolver (same behavior as your warehouse resolver)
def resolve_bin_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)

def resolve_bin_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    """
    Resolve a Bin by code in the user's scope.
    Bin is company-scoped via ctx.company_id; branch scope is derived from its warehouse.
    """
    code = _require_non_empty(code, "Code")
    co_id = getattr(ctx, "company_id", None)

    q = (
        select(
            Bin.id,
            Bin.company_id,
            Warehouse.branch_id,
        )
        .select_from(Bin)
        .join(Warehouse, Warehouse.id == Bin.warehouse_id)
        .where(Bin.code == code)
    )
    if co_id is not None:
        q = q.where(Bin.company_id == co_id)

    row = s.execute(q).first()
    if not row:
        raise NotFound("Bin not found.")

    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id,
    )
    return int(row.id)

# --------------- loader ----------------
def load_bin_detail(s: Session, ctx: AffiliationContext, bin_id: int) -> Dict[str, Any]:
    """
    ERP-style grouped JSON for Bin.
    Shows code, warehouse, item, quantities, and valuation.
    """
    # Header join to fetch everything needed for RBAC + names
    hdr_stmt = (
        select(
            Bin.id, Bin.code,
            Bin.company_id, Bin.item_id, Bin.warehouse_id,
            Bin.actual_qty, Bin.reserved_qty, Bin.ordered_qty,
            Bin.projected_qty, Bin.valuation_rate, Bin.stock_value,

            # Names
            Company.name.label("company_name"),
            Branch.id.label("branch_id"),
            Branch.name.label("branch_name"),
            Warehouse.name.label("warehouse_name"),
            Item.name.label("item_name"),
        )
        .select_from(Bin)
        .join(Warehouse, Warehouse.id == Bin.warehouse_id)
        .join(Company, Company.id == Bin.company_id)
        .outerjoin(Branch, Branch.id == Warehouse.branch_id)
        .join(Item, Item.id == Bin.item_id)
        .where(Bin.id == bin_id)
    )
    row = s.execute(hdr_stmt).mappings().first()
    if not row:
        raise NotFound("Bin not found.")

    # RBAC: company from Bin, branch from Warehouse
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row["company_id"],
        target_branch_id=row["branch_id"],
    )

    identity = {
        "bin_id": int(row["id"]),
        "code": row["code"],
        "company_id": int(row["company_id"]),
        "item_id": int(row["item_id"]),
        "warehouse_id": int(row["warehouse_id"]),
    }

    location = {
        "company_name": row["company_name"],
        "branch_id": int(row["branch_id"]) if row["branch_id"] is not None else None,
        "branch_name": row["branch_name"] or "Global",
        "warehouse_name": row["warehouse_name"],
    }

    item = {
        "item_id": int(row["item_id"]),
        "item_name": row["item_name"],
    }

    quantities = {
        "actual_qty": _f(row["actual_qty"]),
        "reserved_qty": _f(row["reserved_qty"]),
        "ordered_qty": _f(row["ordered_qty"]),
        "projected_qty": _f(row["projected_qty"]),
    }

    valuation = {
        "valuation_rate": _f(row["valuation_rate"]),
        "stock_value": _f(row["stock_value"]),
    }

    # Frappe-style grouped response
    return {
        "identity": identity,
        "location": location,
        "item": item,
        "quantities": quantities,
        "valuation": valuation,
    }
