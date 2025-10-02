# app/application_stock/query_builders/warehouse_detail_builders.py
from __future__ import annotations
from typing import Dict, Any, Optional

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

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


# ---------- resolvers ----------
def resolve_id_strict(_: Session, __: AffiliationContext, v: str) -> int:
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def resolve_warehouse_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    code = (code or "").strip()
    if not code:
        raise BadRequest("Code required.")

    # First find the warehouse
    row = s.execute(
        select(Warehouse.id, Warehouse.company_id, Warehouse.branch_id)
        .where(Warehouse.code == code)
    ).first()

    if not row:
        raise NotFound("Warehouse not found.")

    # Use your existing RBAC system to check access
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id
    )

    return int(row.id)


def resolve_warehouse_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise BadRequest("Name required.")

    # URL decode the name (handles "Goods%20In%20Transit" -> "Goods In Transit")
    import urllib.parse
    decoded_name = urllib.parse.unquote(name)

    # First find the warehouse
    row = s.execute(
        select(Warehouse.id, Warehouse.company_id, Warehouse.branch_id)
        .where(Warehouse.name == decoded_name)
    ).first()

    if not row:
        raise NotFound("Warehouse not found.")

    # Use your existing RBAC system to check access
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=row.company_id,
        target_branch_id=row.branch_id
    )

    return int(row.id)


# ---------- loader ----------
def load_warehouse_detail(s: Session, ctx: AffiliationContext, warehouse_id: int) -> Dict[str, Any]:
    """
    Returns detailed warehouse information in Frappe-style grouped JSON
    """
    # Base warehouse info
    base = s.execute(
        select(
            Warehouse.id, Warehouse.company_id, Warehouse.branch_id,
            Warehouse.code, Warehouse.name, Warehouse.description,
            Warehouse.is_group, Warehouse.status,
            Warehouse.parent_warehouse_id
        ).where(Warehouse.id == warehouse_id)
    ).mappings().first()

    if not base:
        raise NotFound("Warehouse not found.")

    # Use your existing RBAC system - this will handle system admins, company owners, etc.
    ensure_scope_by_ids(
        context=ctx,
        target_company_id=base.company_id,
        target_branch_id=base.branch_id
    )

    # Company and branch info
    company = s.execute(
        select(Company.name).where(Company.id == base.company_id)
    ).scalar()

    branch = None
    if base.branch_id:
        branch = s.execute(
            select(Branch.name).where(Branch.id == base.branch_id)
        ).scalar()

    # Parent warehouse info
    parent = None
    if base.parent_warehouse_id:
        parent = s.execute(
            select(Warehouse.name, Warehouse.code).where(Warehouse.id == base.parent_warehouse_id)
        ).mappings().first()

    # Child warehouses count (if this is a group)
    child_count = 0
    if base.is_group:
        child_count = s.execute(
            select(func.count(Warehouse.id)).where(Warehouse.parent_warehouse_id == warehouse_id)
        ).scalar()

    # Assemble ERP-style response
    identity = {
        "warehouse_id": int(base.id),
        "company_id": int(base.company_id),
        "code": base.code,
        "name": base.name,
        "status": _status_slug(base.status),
        "is_group": bool(base.is_group),
    }

    location = {
        "company": company,
        "branch": branch or "Global",  # ERP-style: show "Global" for company-level warehouses
        "branch_id": int(base.branch_id) if base.branch_id else None,
    }

    hierarchy = {
        "parent_warehouse_id": int(base.parent_warehouse_id) if base.parent_warehouse_id else None,
        "parent_name": parent["name"] if parent else None,
        "parent_code": parent["code"] if parent else None,
        "child_warehouses_count": child_count,
    }

    details = {
        "description": base.description,
    }

    return {
        "identity": identity,
        "location": location,
        "hierarchy": hierarchy,
        "details": details,
    }