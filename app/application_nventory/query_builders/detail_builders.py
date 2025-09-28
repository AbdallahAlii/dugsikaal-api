# app/application_inventory/build_inventory_queries/detail_builders

from __future__ import annotations
from typing import Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, UOMConversion, BranchItemPricing
)
from app.security.rbac_effective import AffiliationContext

# ---- scope helpers ----
def _ensure_company(ctx: AffiliationContext, company_id: int):
    if getattr(ctx, "is_system_admin", False):
        return
    if not any(a.company_id == company_id for a in (ctx.affiliations or [])):
        raise Forbidden("Out of scope for this company.")

def _ensure_branch(ctx: AffiliationContext, company_id: int, branch_id: int):
    _ensure_company(ctx, company_id)
    if getattr(ctx, "is_system_admin", False):
        return
    ok = any(a.company_id == company_id and (a.branch_id is None or a.branch_id == branch_id)
             for a in (ctx.affiliations or []))
    if not ok:
        raise Forbidden("Out of scope for this branch.")

def _first_or_404(session: Session, stmt, label: str) -> dict:
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


def resolve_id_strict(s, ctx, v: str) -> int:
    # accept only digits (trim spaces), fail fast with a friendly msg
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)
# ---- resolvers (string identifier -> record_id) ----
def resolve_brand_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    stmt = select(Brand.id, Brand.company_id).where(Brand.name == name)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Brand not found.")
    _ensure_company(ctx, row.company_id)
    return int(row.id)

def resolve_uom_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    stmt = select(UnitOfMeasure.id, UnitOfMeasure.company_id).where(UnitOfMeasure.name == name)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("UOM not found.")
    _ensure_company(ctx, row.company_id)
    return int(row.id)

def resolve_item_by_sku(s: Session, ctx: AffiliationContext, sku: str) -> int:
    stmt = select(Item.id, Item.company_id).where(Item.sku == sku)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item not found.")
    _ensure_company(ctx, row.company_id)
    return int(row.id)

def resolve_item_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    stmt = select(Item.id, Item.company_id).where(Item.name == name)
    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item not found.")
    _ensure_company(ctx, row.company_id)
    return int(row.id)

# ---- loaders (record_id -> JSON) ----
def load_brand(s: Session, ctx: AffiliationContext, brand_id: int) -> Dict[str, Any]:
    stmt = select(Brand.id, Brand.name, Brand.company_id, Brand.status).where(Brand.id == brand_id)
    data = _first_or_404(s, stmt, "Brand")
    _ensure_company(ctx, data["company_id"])
    return data

def load_uom(s: Session, ctx: AffiliationContext, uom_id: int) -> Dict[str, Any]:
    stmt = select(UnitOfMeasure.id, UnitOfMeasure.name, UnitOfMeasure.symbol,
                  UnitOfMeasure.company_id, UnitOfMeasure.status).where(UnitOfMeasure.id == uom_id)
    data = _first_or_404(s, stmt, "UOM")
    _ensure_company(ctx, data["company_id"])
    return data

def load_item(s: Session, ctx: AffiliationContext, item_id: int) -> Dict[str, Any]:
    # assemble cross-model fields (brand name, base uom symbol)
    stmt = (
        select(
            Item.id, Item.name, Item.sku, Item.item_type, Item.description,
            Item.company_id, Item.brand_id, Item.base_uom_id, Item.status
        )
        .where(Item.id == item_id)
    )
    item = _first_or_404(s, stmt, "Item")
    _ensure_company(ctx, item["company_id"])

    # join-like fetches (optional)
    brand_name = None
    if item["brand_id"]:
        br = s.execute(select(Brand.name).where(Brand.id == item["brand_id"])).scalar()
        brand_name = br
    uom_symbol = None
    if item["base_uom_id"]:
        u = s.execute(select(UnitOfMeasure.symbol).where(UnitOfMeasure.id == item["base_uom_id"])).scalar()
        uom_symbol = u

    item["brand_name"] = brand_name
    item["base_uom_symbol"] = uom_symbol
    return item

def load_uom_conversion(s: Session, ctx: AffiliationContext, conv_id: int) -> Dict[str, Any]:
    stmt = (
        select(
            UOMConversion.id, UOMConversion.item_id, UOMConversion.from_uom_id,
            UOMConversion.to_uom_id, UOMConversion.conversion_factor, UOMConversion.company_id
        )
        .where(UOMConversion.id == conv_id)
    )
    data = _first_or_404(s, stmt, "UOM Conversion")
    _ensure_company(ctx, data["company_id"])
    return data

def load_branch_price(s: Session, ctx: AffiliationContext, price_id: int) -> Dict[str, Any]:
    stmt = (
        select(
            BranchItemPricing.id, BranchItemPricing.item_id, BranchItemPricing.company_id,
            BranchItemPricing.branch_id, BranchItemPricing.standard_rate, BranchItemPricing.cost
        )
        .where(BranchItemPricing.id == price_id)
    )
    data = _first_or_404(s, stmt, "Branch Item Pricing")
    _ensure_branch(ctx, data["company_id"], data["branch_id"])
    return data

