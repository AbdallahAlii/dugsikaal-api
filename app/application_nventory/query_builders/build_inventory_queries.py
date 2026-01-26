from __future__ import annotations

from sqlalchemy import select, false, desc, asc
from sqlalchemy.orm import Session
from app.security.rbac_effective import AffiliationContext
from werkzeug.exceptions import Forbidden

from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, UOMConversion, ItemGroup, PriceList, ItemPrice
)


def build_brands_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of brands with pagination.
    Returns: id, name, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Brand.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            Brand.id.label("id"),
            Brand.name.label("name"),
            Brand.company_id.label("company_id"),
            Brand.created_at.label("created_at"),
        )
        .where(Brand.company_id == co_id)
        .order_by(desc(Brand.created_at), asc(Brand.name))
        .offset(offset_val)
        .limit(per_page)
    )


def build_uoms_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of units of measure with pagination.
    Returns: id, name, symbol, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(UnitOfMeasure.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            UnitOfMeasure.id.label("id"),
            UnitOfMeasure.name.label("name"),
            UnitOfMeasure.symbol.label("symbol"),
            UnitOfMeasure.company_id.label("company_id"),
            UnitOfMeasure.created_at.label("created_at"),
        )
        .where(UnitOfMeasure.company_id == co_id)
        .order_by(desc(UnitOfMeasure.created_at), asc(UnitOfMeasure.name))
        .offset(offset_val)
        .limit(per_page)
    )


def build_items_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of items with pagination.
    Returns: id, name, sku, item_type, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Item.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            Item.id.label("id"),
            Item.name.label("name"),
            Item.sku.label("sku"),
            Item.item_type.label("item_type"),
            Item.company_id.label("company_id"),
            Item.created_at.label("created_at"),
        )
        .where(Item.company_id == co_id)
        .order_by(desc(Item.created_at), asc(Item.name))
        .offset(offset_val)
        .limit(per_page)
    )


def build_item_groups_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of item groups with pagination.
    Returns ONLY: id, name, parent_name, is_group, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(ItemGroup.id).where(false())

    offset_val = (page - 1) * per_page

    # Parent ItemGroup alias for self-join
    from sqlalchemy.orm import aliased
    ParentGroup = aliased(ItemGroup, name="parent_group")

    return (
        select(
            ItemGroup.id.label("id"),
            ItemGroup.name.label("name"),
            ParentGroup.name.label("parent_name"),  # Only parent name, not ID
            ItemGroup.is_group.label("is_group"),
            ItemGroup.company_id.label("company_id"),
            ItemGroup.created_at.label("created_at"),
        )
        .outerjoin(ParentGroup, ParentGroup.id == ItemGroup.parent_item_group_id)
        .where(ItemGroup.company_id == co_id)
        .order_by(desc(ItemGroup.created_at), asc(ItemGroup.name))
        .offset(offset_val)
        .limit(per_page)
    )


def build_price_lists_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of price lists with pagination.
    Returns ONLY: id, name, list_type, is_active, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(PriceList.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            PriceList.id.label("id"),
            PriceList.name.label("name"),
            PriceList.list_type.label("list_type"),
            PriceList.is_active.label("is_active"),
            PriceList.company_id.label("company_id"),
            PriceList.created_at.label("created_at"),
        )
        .where(PriceList.company_id == co_id)
        .order_by(
            desc(PriceList.is_default),  # Default lists first
            desc(PriceList.created_at),
            asc(PriceList.name)
        )
        .offset(offset_val)
        .limit(per_page)
    )


def build_item_prices_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of item prices with pagination.
    Returns ONLY: id, code, item_name, price_list_name, company_id, created_at
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(ItemPrice.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            ItemPrice.id.label("id"),
            ItemPrice.code.label("code"),
            Item.name.label("item_name"),
            PriceList.name.label("price_list_name"),
            ItemPrice.company_id.label("company_id"),
            ItemPrice.created_at.label("created_at"),
        )
        .join(Item, Item.id == ItemPrice.item_id)
        .join(PriceList, PriceList.id == ItemPrice.price_list_id)
        .where(ItemPrice.company_id == co_id)
        .order_by(desc(ItemPrice.created_at), asc(Item.name))
        .offset(offset_val)
        .limit(per_page)
    )


def build_uom_conversions_query(session: Session, context: AffiliationContext, page: int = 1, per_page: int = 50):
    """
    Company-scoped list of UOM conversions with pagination.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(UOMConversion.id).where(false())

    offset_val = (page - 1) * per_page

    return (
        select(
            UOMConversion.id.label("id"),
            UOMConversion.item_id.label("item_id"),
            UOMConversion.uom_id.label("uom_id"),
            UOMConversion.conversion_factor.label("conversion_factor"),
            UOMConversion.is_active.label("is_active"),
            UOMConversion.company_id.label("company_id"),
            UOMConversion.created_at.label("created_at"),
        )
        .where(UOMConversion.company_id == co_id)
        .order_by(desc(UOMConversion.created_at))
        .offset(offset_val)
        .limit(per_page)
    )