from __future__ import annotations
from sqlalchemy import select, literal, union_all, case, or_, and_, func
from sqlalchemy.orm import Session, aliased
from typing import Mapping, Any

from app.application_nventory.inventory_models import Item, UnitOfMeasure, Brand, UOMConversion, ItemGroup
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext
from config.database import db


# --- Common scoping helpers ---
def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)


def _br(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "branch_id", None)


def _build_meta_description(**fields) -> str:
    """Build meta description from non-empty field values (Frappe-style)"""
    parts = [str(v) for v in fields.values() if v is not None and v != '']
    return ' • '.join(parts) if parts else ''


# --- ITEMS DROPDOWNS ---

def build_items_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All items for company (including inactive) - for admin views
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Item.id.label("value")).where(Item.id == -1)

    # Base query with all relevant fields for meta
    q = (
        select(
            Item.id.label("value"),
            Item.name.label("label"),
            # Meta fields
            Item.sku.label("sku"),
            Item.item_type.label("item_type"),
            Item.status.label("status"),
            UnitOfMeasure.symbol.label("uom_symbol"),
            Brand.name.label("brand_name"),
            Item.created_at.label("created_at"),
        )
        .select_from(Item)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .outerjoin(Brand, Brand.id == Item.brand_id)
        .where(Item.company_id == co_id)
    )

    # Apply filters
    it = params.get("item_type")
    if it:
        q = q.where(Item.item_type == it)

    st = params.get("status")
    if st:
        q = q.where(Item.status == st)
    else:
        # Default to active only if no status filter
        q = q.where(Item.status == StatusEnum.ACTIVE)

    # Order by: active first, then newest first, then name
    q = q.order_by(
        case((Item.status == StatusEnum.ACTIVE, 0), else_=1),  # Active first
        Item.created_at.desc(),  # Newest first (Frappe pattern)
        Item.name.asc()  # Then alphabetically
    )

    return q


def build_active_items_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active items only - for transactions (sales/purchases)
    Optimized for performance with minimal joins
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Item.id.label("value")).where(Item.id == -1)

    q = (
        select(
            Item.id.label("value"),
            Item.name.label("label"),
            # Essential meta only for performance
            Item.sku.label("sku"),
            Item.item_type.label("item_type"),
            UnitOfMeasure.symbol.label("uom_symbol"),
        )
        .select_from(Item)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(
            Item.company_id == co_id,
            Item.status == StatusEnum.ACTIVE  # Only active items
        )
    )

    # Filter by item_type if provided (common in transactions)
    it = params.get("item_type")
    if it:
        q = q.where(Item.item_type == it)

    # Order by: newest first, then name (transaction pattern)
    q = q.order_by(
        Item.created_at.desc(),  # Newest items first
        Item.name.asc()
    )

    return q


# --- UOMS DROPDOWNS ---

def build_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All UOMs for company (including inactive) - for admin views
    """
    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(UnitOfMeasure.id == -1)

    q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),
            UnitOfMeasure.symbol.label("symbol"),
            UnitOfMeasure.status.label("status"),
            UnitOfMeasure.created_at.label("created_at"),
        )
        .where(UnitOfMeasure.company_id == co_id)
    )

    st = params.get("status")
    if st:
        q = q.where(UnitOfMeasure.status == st)
    else:
        q = q.where(UnitOfMeasure.status == StatusEnum.ACTIVE)

    # Order by: active first, then newest, then name
    q = q.order_by(
        case((UnitOfMeasure.status == StatusEnum.ACTIVE, 0), else_=1),
        UnitOfMeasure.created_at.desc(),
        UnitOfMeasure.name.asc()
    )

    return q


def build_active_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active UOMs only - for transactions and forms
    """
    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(UnitOfMeasure.id == -1)

    return (
        select(
            UnitOfMeasure.id.label("value"),
            # Show symbol with name for better UX (Frappe style)
            (UnitOfMeasure.name + " (" + UnitOfMeasure.symbol + ")").label("label"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .where(
            UnitOfMeasure.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
        .order_by(
            UnitOfMeasure.created_at.desc(),  # Newest first
            UnitOfMeasure.name.asc()
        )
    )


# --- BRANDS DROPDOWNS ---

def build_brands_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All brands for company (including inactive) - for admin views
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Brand.id.label("value")).where(Brand.id == -1)

    q = (
        select(
            Brand.id.label("value"),
            Brand.name.label("label"),
            Brand.status.label("status"),
            Brand.created_at.label("created_at"),
        )
        .where(Brand.company_id == co_id)
    )

    st = params.get("status")
    if st:
        q = q.where(Brand.status == st)
    else:
        q = q.where(Brand.status == StatusEnum.ACTIVE)

    # Order by: active first, then newest, then name
    q = q.order_by(
        case((Brand.status == StatusEnum.ACTIVE, 0), else_=1),
        Brand.created_at.desc(),
        Brand.name.asc()
    )

    return q


def build_active_brands_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active brands only - for transactions and forms
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Brand.id.label("value")).where(Brand.id == -1)

    return (
        select(
            Brand.id.label("value"),
            Brand.name.label("label"),
        )
        .where(
            Brand.company_id == co_id,
            Brand.status == StatusEnum.ACTIVE
        )
        .order_by(
            Brand.created_at.desc(),  # Newest first
            Brand.name.asc()
        )
    )


# --- SPECIALIZED DROPDOWNS ---



def build_item_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Returns UOMs valid for a given item: base UOM + conversion UOMs
    Optimized for transaction forms
    """
    item_id = params.get("item_id")
    if not item_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    # Base UOM (always available)
    base_q = (
        select(
            UnitOfMeasure.id.label("value"),
            # Label: "Base UOM Name (symbol)"
            (UnitOfMeasure.name + " (Base - " + UnitOfMeasure.symbol + ")").label("label"),
            literal(1.0).label("factor"),
            literal(True).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(Item)
        .join(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(
            Item.id == int(item_id),
            Item.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
    )

    # Conversion UOMs (active only)
    conv_q = (
        select(
            UnitOfMeasure.id.label("value"),
            # Label: "UOM Name (symbol) - Factor: X"
            (
                    UnitOfMeasure.name + " (" + UnitOfMeasure.symbol +
                    ") - Factor: " + func.cast(UOMConversion.conversion_factor, db.String)
            ).label("label"),
            UOMConversion.conversion_factor.label("factor"),
            literal(False).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(UOMConversion)
        .join(UnitOfMeasure, UnitOfMeasure.id == UOMConversion.to_uom_id)
        .where(
            UOMConversion.item_id == int(item_id),
            UOMConversion.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
    )

    u = union_all(base_q, conv_q).subquery()

    # Order: base first, then alphabetical
    return (
        select(u.c.value, u.c.label, u.c.factor, u.c.is_base, u.c.symbol)
        .order_by(
            u.c.is_base.desc(),  # Base UOM first
            u.c.label.asc()  # Then alphabetically
        )
    )



def build_item_groups_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Minimal Item Group dropdown (both folders and leaves).
    Columns:
      - value: id
      - label: "<code> - <name>"
      - is_group: bool (so UI can show folder/dot icon)

    Optional filters in `params`:
      - only_groups: 1/0 (or True/False)
      - only_leaves: 1/0 (or True/False)
      - parent_id: int  -> restrict to children of this parent
      - root_only: 1/0  -> only groups whose parent is NULL
      - q: str          -> search name/code (ilike)
    """
    co_id = _co(ctx)
    if not co_id:
        return select(ItemGroup.id.label("value")).where(literal(False))  # empty

    q = (
        select(
            ItemGroup.id.label("value"),
            (ItemGroup.code + " - " + ItemGroup.name).label("label"),
            ItemGroup.is_group.label("is_group"),
        )
        .where(ItemGroup.company_id == co_id)
    )

    # Filters
    only_groups = params.get("only_groups")
    only_leaves = params.get("only_leaves")
    parent_id = params.get("parent_id")
    root_only = params.get("root_only")
    term = (params.get("q") or "").strip()

    if only_groups:
        q = q.where(ItemGroup.is_group.is_(True))
    if only_leaves:
        q = q.where(ItemGroup.is_group.is_(False))
    if parent_id is not None:
        try:
            pid = int(parent_id)
            q = q.where(ItemGroup.parent_item_group_id == pid)
        except Exception:
            # ignore bad parent_id; returns nothing
            return select(ItemGroup.id.label("value")).where(literal(False))
    if root_only:
        q = q.where(ItemGroup.parent_item_group_id.is_(None))
    if term:
        like = f"%{term}%"
        q = q.where(or_(ItemGroup.name.ilike(like), ItemGroup.code.ilike(like)))

    # Order: groups first (nice UX), then code, then name
    q = q.order_by(
        case((ItemGroup.is_group.is_(True), 0), else_=1),
        ItemGroup.code.asc(),
        ItemGroup.name.asc(),
    )
    return q


def build_item_group_parents_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Convenience wrapper: groups only (folders), minimal fields.
    Accepts same params as build_item_groups_dropdown; we force only_groups=1.
    """
    params = dict(params or {})
    params["only_groups"] = True
    return build_item_groups_dropdown(session, ctx, params)


def build_item_group_leaves_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Convenience wrapper: leaves only (non-groups), minimal fields.
    Accepts same params as build_item_groups_dropdown; we force only_leaves=1.
    """
    params = dict(params or {})
    params["only_leaves"] = True
    return build_item_groups_dropdown(session, ctx, params)


