from __future__ import annotations
from typing import Dict, Any
from datetime import datetime, date

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Forbidden, BadRequest

from app.application_nventory.inventory_models import (
    Brand, UnitOfMeasure, Item, UOMConversion, ItemGroup, PriceList, ItemPrice
)
from app.application_accounting.chart_of_accounts.models import Account
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Import your date helper functions
from app.common.date_utils import format_date_out, parse_date_flex


# ---- Helper functions ----
def _first_or_404(session: Session, stmt, label: str) -> dict:
    """Get first result or raise 404."""
    row = session.execute(stmt).mappings().first()
    if not row:
        raise NotFound(f"{label} not found.")
    return dict(row)


def _ensure_company_access(ctx: AffiliationContext, company_id: int) -> None:
    """
    ✅ Rule: Any user in the same company can see ALL data,
    regardless of branch. Users from other companies cannot see this data.
    System Admin bypass is handled by ensure_scope_by_ids.

    IMPORTANT: This only checks COMPANY scope, not permissions!
    """
    ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=None)


def resolve_id_strict(s, ctx, v: str) -> int:
    """Resolve strict integer ID."""
    vv = (v or "").strip()
    if not vv.isdigit():
        raise BadRequest("Invalid identifier.")
    return int(vv)


def _get_user_company_id(ctx: AffiliationContext) -> int:
    """Get user's company_id from context, raising proper error if missing."""
    company_id = getattr(ctx, "company_id", None)
    if not company_id and not getattr(ctx, "is_system_admin", False):
        # System admins can work without company context for some operations
        raise BadRequest("Company context is required for this operation.")
    return company_id


def _format_datetime_fields(data: dict, date_fields: list = None) -> dict:
    """Format datetime fields in the data dictionary using format_date_out helper."""
    if date_fields is None:
        date_fields = ['created_at', 'updated_at', 'valid_from', 'valid_upto']

    for field in date_fields:
        if field in data and data[field] is not None:
            data[field] = format_date_out(data[field])

    return data


def _format_nested_datetime_fields(data: dict, nested_paths: list) -> dict:
    """Format datetime fields in nested dictionaries."""
    for path in nested_paths:
        parts = path.split('.')
        current = data

        try:
            # Navigate to the nested dictionary
            for part in parts[:-1]:
                if current.get(part) is None:
                    break
                current = current[part]

            # Format the date field if it exists
            last_part = parts[-1]
            if last_part in current and current[last_part] is not None:
                current[last_part] = format_date_out(current[last_part])
        except (KeyError, AttributeError, TypeError):
            continue

    return data


# ---- Item Group resolvers and loaders ----
def resolve_item_group_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """Resolve item group by name WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        # System admin without company context - get any item group by name
        stmt = select(ItemGroup.id, ItemGroup.company_id).where(ItemGroup.name == name)
    else:
        # Regular user OR system admin with company context - filter by company
        stmt = select(ItemGroup.id, ItemGroup.company_id).where(
            and_(
                ItemGroup.name == name,
                ItemGroup.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item Group not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def load_item_group(s: Session, ctx: AffiliationContext, item_group_id: int) -> Dict[str, Any]:
    """Load complete item group details with ERPNext-style format."""
    # Main query with all fields
    stmt = (
        select(
            ItemGroup.id,
            ItemGroup.company_id,
            ItemGroup.parent_item_group_id,
            ItemGroup.name,
            ItemGroup.code,
            ItemGroup.is_group,
            ItemGroup.default_expense_account_id,
            ItemGroup.default_income_account_id,
            ItemGroup.default_inventory_account_id,
            ItemGroup.created_at,
            ItemGroup.updated_at,
        )
        .where(ItemGroup.id == item_group_id)
    )

    item_group = _first_or_404(s, stmt, "Item Group")

    # Check company access BEFORE doing any additional queries
    _ensure_company_access(ctx, item_group["company_id"])

    # Get parent name if exists
    parent_name = None
    if item_group["parent_item_group_id"]:
        parent_name = s.execute(
            select(ItemGroup.name).where(ItemGroup.id == item_group["parent_item_group_id"])
        ).scalar()

    # Get account details in batch query
    account_ids = [
        item_group["default_expense_account_id"],
        item_group["default_income_account_id"],
        item_group["default_inventory_account_id"]
    ]
    valid_account_ids = [aid for aid in account_ids if aid]

    accounts = {}
    if valid_account_ids:
        account_rows = s.execute(
            select(Account.id, Account.name, Account.code)
            .where(Account.id.in_(valid_account_ids))
        ).fetchall()

        accounts = {row.id: {"name": row.name, "code": row.code} for row in account_rows}

    # ERPNext-style response
    result = {
        "id": item_group["id"],
        "company_id": item_group["company_id"],
        "name": item_group["name"],
        "code": item_group["code"],
        "is_group": item_group["is_group"],
        "parent_item_group": {
            "id": item_group["parent_item_group_id"],
            "name": parent_name
        } if item_group["parent_item_group_id"] else None,
        "default_accounts": {
            "expense": {
                "id": item_group["default_expense_account_id"],
                "name": accounts.get(item_group["default_expense_account_id"], {}).get("name"),
                "code": accounts.get(item_group["default_expense_account_id"], {}).get("code")
            } if item_group["default_expense_account_id"] else None,
            "income": {
                "id": item_group["default_income_account_id"],
                "name": accounts.get(item_group["default_income_account_id"], {}).get("name"),
                "code": accounts.get(item_group["default_income_account_id"], {}).get("code")
            } if item_group["default_income_account_id"] else None,
            "inventory": {
                "id": item_group["default_inventory_account_id"],
                "name": accounts.get(item_group["default_inventory_account_id"], {}).get("name"),
                "code": accounts.get(item_group["default_inventory_account_id"], {}).get("code")
            } if item_group["default_inventory_account_id"] else None,
        },
        "created_at": item_group["created_at"],
        "updated_at": item_group["updated_at"]
    }

    # Format date fields
    return _format_datetime_fields(result)


# ---- Price List resolvers and loaders ----
def resolve_price_list_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """Resolve price list by name WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(PriceList.id, PriceList.company_id).where(PriceList.name == name)
    else:
        stmt = select(PriceList.id, PriceList.company_id).where(
            and_(
                PriceList.name == name,
                PriceList.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Price List not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def load_price_list(s: Session, ctx: AffiliationContext, price_list_id: int) -> Dict[str, Any]:
    """Load complete price list details."""
    stmt = (
        select(
            PriceList.id,
            PriceList.company_id,
            PriceList.name,
            PriceList.list_type,
            PriceList.price_not_uom_dependent,
            PriceList.is_active,
            PriceList.is_default,
            PriceList.created_at,
            PriceList.updated_at,
        )
        .where(PriceList.id == price_list_id)
    )

    price_list = _first_or_404(s, stmt, "Price List")
    _ensure_company_access(ctx, price_list["company_id"])

    result = {
        "id": price_list["id"],
        "company_id": price_list["company_id"],
        "name": price_list["name"],
        "list_type": price_list["list_type"],
        "price_not_uom_dependent": price_list["price_not_uom_dependent"],
        "is_active": price_list["is_active"],
        "is_default": price_list["is_default"],
        "created_at": price_list["created_at"],
        "updated_at": price_list["updated_at"]
    }

    # Format date fields
    return _format_datetime_fields(result)


# ---- Item Price resolvers and loaders ----
def resolve_item_price_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    """Resolve item price by code WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(ItemPrice.id, ItemPrice.company_id).where(ItemPrice.code == code)
    else:
        stmt = select(ItemPrice.id, ItemPrice.company_id).where(
            and_(
                ItemPrice.code == code,
                ItemPrice.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item Price not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def load_item_price(s: Session, ctx: AffiliationContext, item_price_id: int) -> Dict[str, Any]:
    """Load complete item price details in ERPNext-style format."""
    # Main query with all related data (efficient single query)
    stmt = (
        select(
            ItemPrice.id,
            ItemPrice.code,
            ItemPrice.company_id,
            ItemPrice.item_id,
            ItemPrice.price_list_id,
            ItemPrice.branch_id,
            ItemPrice.uom_id,
            ItemPrice.rate,
            ItemPrice.valid_from,
            ItemPrice.valid_upto,
            ItemPrice.created_at,
            ItemPrice.updated_at,
            Item.name.label("item_name"),
            Item.sku.label("item_sku"),
            PriceList.name.label("price_list_name"),
            PriceList.list_type.label("price_list_type"),
            UnitOfMeasure.name.label("uom_name"),
            UnitOfMeasure.symbol.label("uom_symbol"),
        )
        .join(Item, Item.id == ItemPrice.item_id)
        .join(PriceList, PriceList.id == ItemPrice.price_list_id)
        .outerjoin(UnitOfMeasure, UnitOfMeasure.id == ItemPrice.uom_id)
        .where(ItemPrice.id == item_price_id)
    )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Item Price not found.")

    _ensure_company_access(ctx, row["company_id"])

    # ERPNext-style response
    result = {
        "id": row["id"],
        "code": row["code"],
        "company_id": row["company_id"],
        "item": {
            "id": row["item_id"],
            "name": row["item_name"],
            "sku": row["item_sku"]
        },
        "price_list": {
            "id": row["price_list_id"],
            "name": row["price_list_name"],
            "list_type": row["price_list_type"]
        },
        "branch": {
            "id": row["branch_id"]
        } if row["branch_id"] else None,
        "uom": {
            "id": row["uom_id"],
            "name": row["uom_name"],
            "symbol": row["uom_symbol"]
        } if row["uom_id"] else None,
        "rate": float(row["rate"]) if row["rate"] else 0.0,
        "validity": {
            "from": row["valid_from"],
            "upto": row["valid_upto"]
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

    # Format top-level date fields
    result = _format_datetime_fields(result)

    # Format nested date fields in validity
    if result.get("validity"):
        result["validity"]["from"] = format_date_out(result["validity"]["from"])
        result["validity"]["upto"] = format_date_out(result["validity"]["upto"])

    return result


# ---- Updated resolvers with COMPANY FILTER ----
def resolve_brand_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """Resolve brand by name WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(Brand.id, Brand.company_id).where(Brand.name == name)
    else:
        stmt = select(Brand.id, Brand.company_id).where(
            and_(
                Brand.name == name,
                Brand.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Brand not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def resolve_uom_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """Resolve UOM by name WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(UnitOfMeasure.id, UnitOfMeasure.company_id).where(UnitOfMeasure.name == name)
    else:
        stmt = select(UnitOfMeasure.id, UnitOfMeasure.company_id).where(
            and_(
                UnitOfMeasure.name == name,
                UnitOfMeasure.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("UOM not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def resolve_item_by_sku(s: Session, ctx: AffiliationContext, sku: str) -> int:
    """Resolve item by SKU WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(Item.id, Item.company_id).where(Item.sku == sku)
    else:
        stmt = select(Item.id, Item.company_id).where(
            and_(
                Item.sku == sku,
                Item.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def resolve_item_by_name(s: Session, ctx: AffiliationContext, name: str) -> int:
    """Resolve item by name WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(Item.id, Item.company_id).where(Item.name == name)
    else:
        stmt = select(Item.id, Item.company_id).where(
            and_(
                Item.name == name,
                Item.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


def resolve_item_group_by_code(s: Session, ctx: AffiliationContext, code: str) -> int:
    """Resolve item group by code WITH COMPANY FILTER."""
    user_company_id = _get_user_company_id(ctx)

    if getattr(ctx, "is_system_admin", False) and not user_company_id:
        stmt = select(ItemGroup.id, ItemGroup.company_id).where(ItemGroup.code == code)
    else:
        stmt = select(ItemGroup.id, ItemGroup.company_id).where(
            and_(
                ItemGroup.code == code,
                ItemGroup.company_id == user_company_id
            )
        )

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Item Group not found.")

    _ensure_company_access(ctx, row.company_id)
    return int(row.id)


# ---- Existing loaders (keep these) ----
def load_brand(s: Session, ctx: AffiliationContext, brand_id: int) -> Dict[str, Any]:
    stmt = select(
        Brand.id,
        Brand.name,
        Brand.company_id,
        Brand.status,
        Brand.created_at,  # Add created_at
        Brand.updated_at  # Add updated_at
    ).where(Brand.id == brand_id)

    data = _first_or_404(s, stmt, "Brand")
    _ensure_company_access(ctx, data["company_id"])

    # Format date fields
    return _format_datetime_fields(data)


def load_uom(s: Session, ctx: AffiliationContext, uom_id: int) -> Dict[str, Any]:
    stmt = select(
        UnitOfMeasure.id,
        UnitOfMeasure.name,
        UnitOfMeasure.symbol,
        UnitOfMeasure.company_id,
        UnitOfMeasure.status,
        UnitOfMeasure.created_at,  # Add created_at
        UnitOfMeasure.updated_at  # Add updated_at
    ).where(UnitOfMeasure.id == uom_id)

    data = _first_or_404(s, stmt, "UOM")
    _ensure_company_access(ctx, data["company_id"])

    # Format date fields
    return _format_datetime_fields(data)


def load_uom_conversion(s: Session, ctx: AffiliationContext, conv_id: int) -> Dict[str, Any]:
    stmt = (
        select(
            UOMConversion.id,
            UOMConversion.item_id,
            UOMConversion.uom_id,
            UOMConversion.conversion_factor,
            UOMConversion.is_active,
            UOMConversion.company_id,
            UOMConversion.created_at,  # Add created_at
            UOMConversion.updated_at  # Add updated_at
        )
        .where(UOMConversion.id == conv_id)
    )

    data = _first_or_404(s, stmt, "UOM Conversion")
    _ensure_company_access(ctx, data["company_id"])

    # Format date fields
    return _format_datetime_fields(data)


def load_item_detail(s: Session, ctx: AffiliationContext, item_id: int) -> dict:
    """ERP-style detail for Item (optimized version)."""
    # Main query with all necessary joins
    stmt = (
        select(
            Item.id,
            Item.company_id,
            Item.name,
            Item.sku,
            Item.item_type,
            Item.status,
            Item.description,
            Item.is_fixed_asset,
            Item.asset_category_id,
            Item.item_group_id,
            Item.brand_id,
            Item.base_uom_id,
            Item.created_at,  # Add created_at
            Item.updated_at,  # Add updated_at
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

    # Check company access BEFORE doing any additional queries
    _ensure_company_access(ctx, row["company_id"])

    # UOM conversions (batch query for performance)
    conv_stmt = (
        select(
            UOMConversion.id,
            UOMConversion.uom_id,
            UnitOfMeasure.name.label("uom_name"),
            UnitOfMeasure.symbol.label("uom_symbol"),
            UOMConversion.conversion_factor.label("factor"),
            UOMConversion.is_active,
            UOMConversion.created_at,  # Add created_at
            UOMConversion.updated_at,  # Add updated_at
        )
        .select_from(UOMConversion)
        .join(UnitOfMeasure, UnitOfMeasure.id == UOMConversion.uom_id)
        .where(UOMConversion.item_id == item_id)
        .order_by(UOMConversion.is_active.desc(), UnitOfMeasure.name.asc())
    )
    conversions = []
    for r in s.execute(conv_stmt).mappings().all():
        conv_data = dict(r)
        # Format date fields in each conversion
        conv_data["created_at"] = format_date_out(conv_data.get("created_at"))
        conv_data["updated_at"] = format_date_out(conv_data.get("updated_at"))
        conversions.append(conv_data)

    # Compose ERP-style grouped payload
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
        } if row["brand_id"] else None,
        "uom": {
            "base_uom_id": row["base_uom_id"],
            "base_uom_name": row["base_uom_name"],
            "base_uom_symbol": row["base_uom_symbol"],
            "conversions": conversions,
        },
        "asset": {
            "is_fixed_asset": bool(row["is_fixed_asset"]),
            "asset_category_id": row["asset_category_id"],
        } if bool(row["is_fixed_asset"]) or row["asset_category_id"] else {
            "is_fixed_asset": False
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

    # Remove None values and format date fields
    result = {k: v for k, v in data.items() if v is not None}

    # Format date fields
    return _format_datetime_fields(result)