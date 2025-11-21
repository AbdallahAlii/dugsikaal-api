# app/application_inventory/build_inventory_queries/detail_builders

from __future__ import annotations
from typing import Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, UOMConversion, ItemGroup
)
from app.security.rbac_effective import AffiliationContext
from app.application_accounting.chart_of_accounts.assets_model import AssetCategory
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

def load_item_detail(s: Session, ctx: AffiliationContext, item_id: int) -> dict:
    """
    ERP-style detail for Item:
    - Basic: id, name, sku, item_type, status, description
    - Group: item_group (id, code, name, is_group)
    - Brand: id, name
    - UOM: base uom (id, name, symbol)
    - Asset: is_fixed_asset, asset_category (id, name)
    - Conversions: list of {id, uom_id, uom_name, uom_symbol, factor, is_active}
    """
    stmt = (
        select(
            Item.id, Item.company_id,
            Item.id, Item.company_id,
            Item.name, Item.sku, Item.item_type, Item.status, Item.description,
            Item.is_fixed_asset, Item.asset_category_id,
            Item.item_group_id, Item.brand_id, Item.base_uom_id,
            ItemGroup.code.label("item_group_code"),
            ItemGroup.name.label("item_group_name"),
            ItemGroup.is_group.label("item_group_is_group"),
            Brand.name.label("brand_name"),
            UnitOfMeasure.name.label("base_uom_name"),
            UnitOfMeasure.symbol.label("base_uom_symbol"),

        )
        .select_from(Item)
        .join(ItemGroup, ItemGroup.id == Item.item_group_id)
        .outerjoin(Brand, Brand.id == Item.brand_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)

        .where(Item.id == item_id)
    )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Item not found.")
    _ensure_company(ctx, row["company_id"])

    # UOM conversions (active first, then by name)
    conv_stmt = (
        select(
            UOMConversion.id,
            UOMConversion.uom_id,
            UnitOfMeasure.name.label("uom_name"),
            UnitOfMeasure.symbol.label("uom_symbol"),
            UOMConversion.conversion_factor.label("factor"),
            UOMConversion.is_active,
        )
        .select_from(UOMConversion)
        .join(UnitOfMeasure, UnitOfMeasure.id == UOMConversion.uom_id)
        .where(UOMConversion.item_id == item_id)
        .order_by(UOMConversion.is_active.desc(), UnitOfMeasure.name.asc())
    )
    conversions = [dict(r) for r in s.execute(conv_stmt).mappings().all()]

    # Compose ERP-style grouped payload (only include keys that exist)
    def keep(v):  # drop Nones
        return v is not None

    data = {
        "id": row["id"],
        "company_id": row["company_id"],
        "display": {
            "name": row["name"],
            "sku": row["sku"],
            "item_type": row["item_type"],
            "status": row["status"],
            "description": row["description"],
        },
        "group": {
            "id": row["item_group_id"],
            "code": row["item_group_code"],
            "name": row["item_group_name"],
            "is_group": row["item_group_is_group"],
        },
        "brand": {
            "id": row["brand_id"],
            "name": row["brand_name"],
        } if keep(row["brand_id"]) or keep(row["brand_name"]) else None,
        "uom": {
            "base_uom_id": row["base_uom_id"],
            "base_uom_name": row["base_uom_name"],
            "base_uom_symbol": row["base_uom_symbol"],
            "conversions": conversions,   # [{id,uom_id,uom_name,uom_symbol,factor,is_active}, ...]
        },
        "asset": {
            "is_fixed_asset": bool(row["is_fixed_asset"]),
            "asset_category_id": row["asset_category_id"],
            "asset_category_name": row["asset_category_name"],
        } if bool(row["is_fixed_asset"]) or keep(row["asset_category_id"]) else {
            "is_fixed_asset": False
        },
    }

    # prune empty sections
    for k in ("brand",):
        if data.get(k) is None:
            data.pop(k, None)

    return data

