# app/application_inventory/build_inventory_queries
from __future__ import annotations

from typing import Set

from sqlalchemy import select, false
from sqlalchemy.orm import Session

from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, UOMConversion, BranchItemPricing
)
from app.security.rbac_effective import AffiliationContext


def _company_only_filter(company_id: int | None):
    """Return a WHERE-clause predicate for company scoping or false() if missing."""
    if company_id is None:
        return false()
    return (Brand.company_id == company_id)  # dummy; caller will replace model attr


def build_brands_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of brands.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Brand.id).where(false())

    return (
        select(
            Brand.id.label("id"),
            Brand.name.label("name"),
            Brand.company_id.label("company_id"),
        )
        .where(Brand.company_id == co_id)
    )


def build_uoms_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of units of measure.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(UnitOfMeasure.id).where(false())

    return (
        select(
            UnitOfMeasure.id.label("id"),
            UnitOfMeasure.name.label("name"),
            UnitOfMeasure.symbol.label("symbol"),
            UnitOfMeasure.company_id.label("company_id"),
        )
        .where(UnitOfMeasure.company_id == co_id)
    )


def build_items_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of items.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(Item.id).where(false())

    return (
        select(
            Item.id.label("id"),
            Item.name.label("name"),
            Item.sku.label("sku"),
            Item.item_type.label("item_type"),
            Item.company_id.label("company_id"),
        )
        .where(Item.company_id == co_id)
    )


def build_uom_conversions_query(session: Session, context: AffiliationContext):
    """
    Company-scoped list of UOM conversions.
    """
    co_id = getattr(context, "company_id", None)
    if co_id is None:
        return select(UOMConversion.id).where(false())

    return (
        select(
            UOMConversion.id.label("id"),
            UOMConversion.item_id.label("item_id"),
            UOMConversion.from_uom_id.label("from_uom_id"),
            UOMConversion.to_uom_id.label("to_uom_id"),
            UOMConversion.company_id.label("company_id"),
        )
        .where(UOMConversion.company_id == co_id)
    )


def build_branch_item_pricing_query(session: Session, context: AffiliationContext):
    """
    Branch-scoped list of pricing:
      - must match user's company
      - branch_id must be in user's branch_ids
    """
    co_id = getattr(context, "company_id", None)
    branch_ids = list(getattr(context, "branch_ids", []) or [])
    if co_id is None or not branch_ids:
        return select(BranchItemPricing.id).where(false())

    return (
        select(
            BranchItemPricing.id.label("id"),
            BranchItemPricing.item_id.label("item_id"),
            BranchItemPricing.company_id.label("company_id"),
            BranchItemPricing.branch_id.label("branch_id"),
            BranchItemPricing.standard_rate.label("standard_rate"),
            BranchItemPricing.cost.label("cost"),
        )
        .where(
            (BranchItemPricing.company_id == co_id) &
            (BranchItemPricing.branch_id.in_(branch_ids))
        )
    )
