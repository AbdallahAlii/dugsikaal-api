from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.application_nventory.inventory_models import (
    Brand,
    Item,
    ItemGroup,
    UOMConversion,
    UnitOfMeasure,
)
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext
from config.database import db


# -----------------------------------------------------------------------------
# Scope helpers
# -----------------------------------------------------------------------------

def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)


# -----------------------------------------------------------------------------
# ITEMS DROPDOWNS
# -----------------------------------------------------------------------------

def build_items_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All items for company (including inactive) - for admin views.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Item.id.label("value")).where(literal(False))

    q = (
        select(
            Item.id.label("value"),
            Item.name.label("label"),

            # meta fields (these become meta.* in API)
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

    it = params.get("item_type")
    if it:
        q = q.where(Item.item_type == it)

    st = params.get("status")
    if st:
        q = q.where(Item.status == st)
    else:
        q = q.where(Item.status == StatusEnum.ACTIVE)

    q = q.order_by(
        case((Item.status == StatusEnum.ACTIVE, 0), else_=1),
        Item.created_at.desc(),
        Item.name.asc(),
    )

    return q


def build_active_items_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active items only - for transactions.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Item.id.label("value")).where(literal(False))

    q = (
        select(
            Item.id.label("value"),
            Item.name.label("label"),

            # meta (minimal)
            Item.sku.label("sku"),
            Item.item_type.label("item_type"),
            UnitOfMeasure.symbol.label("uom_symbol"),
        )
        .select_from(Item)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(
            Item.company_id == co_id,
            Item.status == StatusEnum.ACTIVE,
        )
    )

    it = params.get("item_type")
    if it:
        q = q.where(Item.item_type == it)

    q = q.order_by(
        Item.created_at.desc(),
        Item.name.asc(),
    )

    return q


# -----------------------------------------------------------------------------
# UOMS DROPDOWNS
# -----------------------------------------------------------------------------

def build_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All UOMs for company (including inactive) - admin views.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),

            # meta
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

    q = q.order_by(
        case((UnitOfMeasure.status == StatusEnum.ACTIVE, 0), else_=1),
        UnitOfMeasure.created_at.desc(),
        UnitOfMeasure.name.asc(),
    )

    return q


def build_active_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active UOMs only.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    return (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),

            # meta
            UnitOfMeasure.symbol.label("symbol"),
        )
        .where(
            UnitOfMeasure.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE,
        )
        .order_by(
            UnitOfMeasure.created_at.desc(),
            UnitOfMeasure.name.asc(),
        )
    )


# -----------------------------------------------------------------------------
# BRANDS DROPDOWNS
# -----------------------------------------------------------------------------

def build_brands_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    All brands for company (including inactive) - admin views.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Brand.id.label("value")).where(literal(False))

    q = (
        select(
            Brand.id.label("value"),
            Brand.name.label("label"),

            # meta
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

    q = q.order_by(
        case((Brand.status == StatusEnum.ACTIVE, 0), else_=1),
        Brand.created_at.desc(),
        Brand.name.asc(),
    )

    return q


def build_active_brands_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Active brands only.
    Scoped by ctx.company_id (NOT branch).
    """
    co_id = _co(ctx)
    if not co_id:
        return select(Brand.id.label("value")).where(literal(False))

    return (
        select(
            Brand.id.label("value"),
            Brand.name.label("label"),
        )
        .where(
            Brand.company_id == co_id,
            Brand.status == StatusEnum.ACTIVE,
        )
        .order_by(
            Brand.created_at.desc(),
            Brand.name.asc(),
        )
    )


# -----------------------------------------------------------------------------
# SPECIALIZED DROPDOWNS
# -----------------------------------------------------------------------------

def build_item_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    UOMs valid for a given item: base UOM + conversion UOMs.
    Scoped by ctx.company_id (NOT branch).
    """
    item_id = params.get("item_id")
    if not item_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    co_id = _co(ctx)
    if not co_id:
        return select(UnitOfMeasure.id.label("value")).where(literal(False))

    base_q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),

            # meta
            literal(1.0).label("factor"),
            literal(True).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(Item)
        .join(UnitOfMeasure, UnitOfMeasure.id == Item.base_uom_id)
        .where(
            Item.id == int(item_id),
            Item.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE,
        )
    )

    conv_q = (
        select(
            UnitOfMeasure.id.label("value"),
            UnitOfMeasure.name.label("label"),

            # meta
            UOMConversion.conversion_factor.label("factor"),
            literal(False).label("is_base"),
            UnitOfMeasure.symbol.label("symbol"),
        )
        .select_from(UOMConversion)
        .join(UnitOfMeasure, UnitOfMeasure.id == UOMConversion.to_uom_id)
        .where(
            UOMConversion.item_id == int(item_id),
            UOMConversion.company_id == co_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE,
        )
    )

    u = union_all(base_q, conv_q).subquery()

    return (
        select(
            u.c.value,
            u.c.label,
            u.c.factor,
            u.c.is_base,
            u.c.symbol,
        )
        .order_by(
            u.c.is_base.desc(),
            u.c.label.asc(),
        )
    )


def build_item_groups_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Item Group dropdown.

    ✅ label: ONLY name (clean)
    ✅ meta: code, is_group

    Optional filters in `params`:
      - only_groups: 1/0
      - only_leaves: 1/0
      - parent_id: int
      - root_only: 1/0
      - q: str (search name/code)
    """
    co_id = _co(ctx)
    if not co_id:
        return select(ItemGroup.id.label("value")).where(literal(False))

    q = (
        select(
            ItemGroup.id.label("value"),
            ItemGroup.name.label("label"),

            # meta
            ItemGroup.code.label("code"),
            ItemGroup.is_group.label("is_group"),
        )
        .where(ItemGroup.company_id == co_id)
    )

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
            return select(ItemGroup.id.label("value")).where(literal(False))

    if root_only:
        q = q.where(ItemGroup.parent_item_group_id.is_(None))

    if term:
        like = f"%{term}%"
        q = q.where(or_(ItemGroup.name.ilike(like), ItemGroup.code.ilike(like)))

    q = q.order_by(
        case((ItemGroup.is_group.is_(True), 0), else_=1),
        ItemGroup.code.asc(),
        ItemGroup.name.asc(),
    )

    return q


def build_item_group_parents_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    params = dict(params or {})
    params["only_groups"] = True
    return build_item_groups_dropdown(session, ctx, params)


def build_item_group_leaves_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    params = dict(params or {})
    params["only_leaves"] = True
    return build_item_groups_dropdown(session, ctx, params)
