# app/application_inventory/dropdown_builders.py
from __future__ import annotations
from sqlalchemy import select, literal, union_all, case
from sqlalchemy.orm import Session
from typing import Mapping, Any

from app.application_nventory.inventory_models import Item, UnitOfMeasure, Brand, BranchItemPricing, UOMConversion
from app.security.rbac_effective import AffiliationContext


# --- Common scoping helpers ---
def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)

def _br(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "branch_id", None)

# Items (company-scoped): value=item.id label=item.name meta: sku, base uom
def build_items_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    co_id = _co(ctx)
    if not co_id:
        # empty select
        return select(Item.id.label("value")).where(Item.id == -1)

    q = (
        select(
            Item.id.label("value"),
            Item.name.label("label"),
            Item.sku.label("sku"),
            UnitOfMeasure.name.label("base_uom_name"),
            UnitOfMeasure.symbol.label("base_uom_symbol"),
        )
        .select_from(Item)
        .join(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(Item.company_id == co_id)
        .order_by(Item.name.asc())
    )
    # optional filter by item_type/status passed via params
    it = params.get("item_type")
    if it:
        q = q.where(Item.item_type == it)
    st = params.get("status")
    if st:
        q = q.where(Item.status == st)
    return q

# UOMs (company-scoped)
def build_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(UnitOfMeasure.id == -1)
    return (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .where(UnitOfMeasure.company_id == co_id)
        .order_by(UnitOfMeasure.name.asc())
    )

# Brands (company-scoped)
def build_brands_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    co_id = _co(ctx)
    if not co_id:
        return select(Brand.id.label("value")).where(Brand.id == -1)
    return (
        select(
            Brand.id.label("value"),
            Brand.name.label("label"),
        )
        .where(Brand.company_id == co_id)
        .order_by(Brand.name.asc())
    )

# Prices (dependent on branch & item_id) – used for “choose price for item” kind of dropdowns
def build_branch_prices_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    co_id = _co(ctx)
    br_id = _br(ctx)
    item_id = params.get("item_id")
    if not (co_id and br_id and item_id):
        return select(BranchItemPricing.id.label("value")).where(BranchItemPricing.id == -1)

    return (
        select(
            BranchItemPricing.id.label("value"),
            BranchItemPricing.standard_rate.label("label"),  # label shows the rate
            BranchItemPricing.cost.label("cost"),
        )
        .where(
            BranchItemPricing.company_id == co_id,
            BranchItemPricing.branch_id == br_id,
            BranchItemPricing.item_id == int(item_id),
        )
        .order_by(BranchItemPricing.standard_rate.asc())
    )

def build_item_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Returns only the UOMs valid for a given item:
      - the base UOM
      - all UOMs that have a conversion mapping for that item
    Expects: params['item_id'] (required)
    """
    item_id = params.get("item_id")
    if not item_id:
        # empty select (enforce dependency)
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    # base UOM row
    base_q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),
            literal(1.0).label("factor"),             # base factor = 1
            literal(True).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(Item)
        .join(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(Item.id == int(item_id))
    )

    # conversion UOM rows (to_uom_id is the target “buy/sell” UOM)
    conv_q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),
            UOMConversion.conversion_factor.label("factor"),
            literal(False).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(UOMConversion)
        .join(UnitOfMeasure, UnitOfMeasure.id == UOMConversion.to_uom_id)
        .where(UOMConversion.item_id == int(item_id))
    )

    u = union_all(base_q, conv_q).subquery()

    # show base first, then alphabetical by label
    return (
        select(u.c.value, u.c.label, u.c.factor, u.c.is_base, u.c.symbol)
        .order_by(
            # base first
            case((u.c.is_base.is_(True), 0), else_=1),
            u.c.label.asc(),
        )
    )