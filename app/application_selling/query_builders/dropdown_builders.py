from __future__ import annotations
from typing import Mapping, Any

from sqlalchemy import select, literal, union_all, case, or_, func
from sqlalchemy.orm import Session, aliased

from app.application_nventory.inventory_models import Item, UnitOfMeasure, UOMConversion
from app.common.models.base import StatusEnum
from app.security.rbac_effective import AffiliationContext

# ------------------------------- helpers -----------------------------------

def _co(ctx: AffiliationContext) -> int | None:
    return getattr(ctx, "company_id", None)

def _q(params: Mapping[str, Any]) -> str:
    return (params.get("q") or "").strip()

def _label_expr(mode: str | None, UOM: UnitOfMeasure):
    """
    Decide how to render the short label:
      - "symbol"  -> use symbol only (e.g., "pcs")
      - default   -> use name only (e.g., "Pieces")
    """
    if (mode or "").lower() == "symbol":
        return UOM.symbol
    return UOM.name

# ------------------------ ITEM-SPECIFIC SALES UOMs -------------------------

def build_item_sales_uoms_dropdown(session: Session, ctx: AffiliationContext, params: Mapping[str, Any]):
    """
    Returns only the UOMs valid for a given item (Selling screen):
      - Base UOM (factor=1, is_base=True)
      - All ACTIVE conversion UOMs for that item (is_base=False)

    The **label is compact** (name by default; pass label_mode=symbol to use symbols).
    Extra info is exposed via meta fields (factor, is_base, symbol).
    """
    co_id = _co(ctx)
    item_id = params.get("item_id")
    if not co_id or item_id in (None, ""):
        return select(UnitOfMeasure.id.label("value")).where(UnitOfMeasure.id == -1)

    try:
        item_id_int = int(item_id)
    except Exception:
        return select(UnitOfMeasure.id.label("value")).where(UnitOfMeasure.id == -1)

    label_mode = (params.get("label_mode") or "").lower()

    BaseUOM = aliased(UnitOfMeasure)
    ConvUOM = aliased(UnitOfMeasure)

    # label expressions (short)
    base_label = _label_expr(label_mode, BaseUOM)
    conv_label = _label_expr(label_mode, ConvUOM)

    # Base UOM row (label is short; details go in meta)
    base_q = (
        select(
            BaseUOM.id.label("value"),
            base_label.label("label"),
            # meta fields
            literal(1.0).label("factor"),
            literal(True).label("is_base"),
            BaseUOM.symbol.label("symbol"),
        )
        .select_from(Item)
        .join(BaseUOM, BaseUOM.id == Item.base_uom_id)
        .where(
            Item.id == item_id_int,
            Item.company_id == co_id,
            Item.status == StatusEnum.ACTIVE,
            BaseUOM.company_id == co_id,
            BaseUOM.status == StatusEnum.ACTIVE,
        )
    )

    # Conversion UOM rows (active conversions, active UOMs; skip base dup)
    conv_q = (
        select(
            ConvUOM.id.label("value"),
            conv_label.label("label"),
            # meta fields
            UOMConversion.conversion_factor.label("factor"),
            literal(False).label("is_base"),
            ConvUOM.symbol.label("symbol"),
        )
        .select_from(UOMConversion)
        .join(Item, Item.id == UOMConversion.item_id)
        .join(ConvUOM, ConvUOM.id == UOMConversion.uom_id)
        .join(BaseUOM, BaseUOM.id == Item.base_uom_id)
        .where(
            UOMConversion.item_id == item_id_int,
            UOMConversion.is_active.is_(True),
            Item.company_id == co_id,
            Item.status == StatusEnum.ACTIVE,
            ConvUOM.company_id == co_id,
            ConvUOM.status == StatusEnum.ACTIVE,
            BaseUOM.company_id == co_id,
            BaseUOM.status == StatusEnum.ACTIVE,
            ConvUOM.id != Item.base_uom_id,   # avoid duplicate base row
        )
    )

    u = union_all(base_q, conv_q).subquery()

    # Final select (outer search on short label or symbol)
    sel = select(u.c.value, u.c.label, u.c.factor, u.c.is_base, u.c.symbol)

    term = _q(params)
    if term:
        like = f"%{term}%"
        sel = sel.where(or_(u.c.label.ilike(like), u.c.symbol.ilike(like)))

    return sel.order_by(
        case((u.c.is_base.is_(True), 0), else_=1),  # base first
        u.c.label.asc(),
    )
