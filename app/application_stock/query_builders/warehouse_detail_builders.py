from __future__ import annotations

from typing import Dict, Any

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session, aliased
from werkzeug.exceptions import NotFound, BadRequest, Forbidden

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids
from app.application_stock.stock_models import Warehouse
from app.application_org.models.company import Branch, Company


# ---------- utils ----------
def _status_slug(v) -> str:
    s = str(v or "").strip()
    if "." in s:
        s = s.split(".")[-1]
    return (s or "inactive").lower()


def _require_company_ctx(ctx: AffiliationContext) -> int | None:
    """
    For non-system admins, company_id must exist (tenant isolation).
    System Admin bypass is handled by ensure_scope_by_ids, but we still
    need company_id to resolve by company for normal users.
    """
    if getattr(ctx, "is_system_admin", False):
        return None
    co_id = getattr(ctx, "company_id", None)
    if not co_id:
        raise Forbidden("Company context is required.")
    return int(co_id)


# ---------- resolvers ----------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_warehouse_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    """
    Resolve warehouse id by code with strict tenant isolation:
      - Non-system-admin: resolves ONLY inside ctx.company_id
      - System-admin: can resolve any company (still returns first match)
    """
    code = (code or "").strip()
    if not code:
        raise BadRequest("Code required.")

    co_id = _require_company_ctx(ctx)

    q = select(Warehouse.id, Warehouse.company_id).where(
        func.lower(Warehouse.code) == func.lower(code)
    )

    # Tenant-safe resolution (most important fix)
    if co_id is not None:
        q = q.where(Warehouse.company_id == co_id)

    row = s.execute(q.limit(1)).first()
    if not row:
        raise NotFound("Warehouse not found.")

    # Company isolation (system-admin bypass inside)
    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)

    return int(row.id)


def resolve_warehouse_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """
    Resolve warehouse id by name with strict tenant isolation:
      - Non-system-admin: resolves ONLY inside ctx.company_id
      - System-admin: can resolve any company (still returns first match)
    """
    name = (name or "").strip()
    if not name:
        raise BadRequest("Name required.")

    import urllib.parse
    decoded_name = urllib.parse.unquote(name).strip()
    if not decoded_name:
        raise BadRequest("Name required.")

    co_id = _require_company_ctx(ctx)

    q = select(Warehouse.id, Warehouse.company_id).where(
        func.lower(Warehouse.name) == func.lower(decoded_name)
    )

    # Tenant-safe resolution (important)
    if co_id is not None:
        q = q.where(Warehouse.company_id == co_id)

    row = s.execute(q.limit(1)).first()
    if not row:
        raise NotFound("Warehouse not found.")

    ensure_scope_by_ids(context=ctx, target_company_id=row.company_id, target_branch_id=None)

    return int(row.id)


# ---------- loader ----------
def load_warehouse_detail(s: Session, ctx: AffiliationContext, warehouse_id: int) -> Dict[str, Any]:
    """
    Detailed warehouse information (ERP-style grouped JSON)

    RULE (your requirement):
      - Any user within the SAME company can see ALL warehouses in that company
        (global + all branches).
      - No cross-company leakage.
    """

    W = aliased(Warehouse, name="w")
    P = aliased(Warehouse, name="parent_w")
    B = aliased(Branch, name="b")
    C = aliased(Company, name="c")

    # child count as a correlated subquery (fast, single round-trip)
    Child = aliased(Warehouse, name="child_w")
    child_count_sq = (
        select(func.count(Child.id))
        .where(Child.parent_warehouse_id == W.id)
        .correlate(W)
        .scalar_subquery()
    )

    # if not a group, child_count should be 0
    child_count_expr = case(
        (W.is_group.is_(True), child_count_sq),
        else_=0,
    ).label("child_warehouses_count")

    row = s.execute(
        select(
            W.id.label("id"),
            W.company_id.label("company_id"),
            W.branch_id.label("branch_id"),
            W.code.label("code"),
            W.name.label("name"),
            W.description.label("description"),
            W.is_group.label("is_group"),
            W.status.label("status"),
            W.parent_warehouse_id.label("parent_warehouse_id"),

            C.name.label("company_name"),
            B.name.label("branch_name"),

            P.name.label("parent_name"),
            P.code.label("parent_code"),

            child_count_expr,
        )
        .select_from(W)
        .join(C, C.id == W.company_id)
        .outerjoin(B, B.id == W.branch_id)
        .outerjoin(P, P.id == W.parent_warehouse_id)
        .where(W.id == warehouse_id)
        .limit(1)
    ).mappings().first()

    if not row:
        raise NotFound("Warehouse not found.")

    # Enforce company scope only (not branch) — exactly your requirement
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=int(row["company_id"]),
        target_branch_id=None,
    )

    branch_id = row["branch_id"]
    return {
        "identity": {
            "warehouse_id": int(row["id"]),
            "company_id": int(row["company_id"]),
            "code": row["code"],
            "name": row["name"],
            "status": _status_slug(row["status"]),
            "is_group": bool(row["is_group"]),
        },
        "location": {
            "company": row["company_name"],
            "branch": row["branch_name"] or "Global",
            "branch_id": int(branch_id) if branch_id is not None else None,
        },
        "hierarchy": {
            "parent_warehouse_id": int(row["parent_warehouse_id"]) if row["parent_warehouse_id"] else None,
            "parent_name": row["parent_name"] if row["parent_name"] else None,
            "parent_code": row["parent_code"] if row["parent_code"] else None,
            "child_warehouses_count": int(row["child_warehouses_count"] or 0),
        },
        "details": {
            "description": row["description"],
        },
    }
