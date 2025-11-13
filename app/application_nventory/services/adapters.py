# app/application_nventory/services/adapters.py
from __future__ import annotations
from typing import Any, Dict, Optional

from werkzeug.exceptions import BadRequest, NotFound, Forbidden

from app.application_nventory.inventory_services import InventoryService
from app.security.rbac_effective import AffiliationContext
from app.application_nventory.schemas.inventory_schemas import ItemCreate, ItemUpdate

from app.application_nventory.repo.inventory_repo import InventoryRepository
from config.database import db


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build a minimal context for importer calls. In production, prefer reading the
    DataImport row and current session user, then threading g.auth through pipeline.
    """
    company_id = int(row.get("company_id") or 0)
    branch_id = row.get("branch_id")
    branch_id = int(branch_id) if branch_id is not None else None
    user_id = row.get("created_by_id")
    user_id = int(user_id) if user_id is not None else None

    roles = set(row.get("roles") or [])  # optional; your pipeline can inject defaults

    return AffiliationContext(
        company_id=company_id,
        branch_id=branch_id,
        user_id=user_id,
        roles=roles
    )


def create_item_via_import(row: Dict[str, Any]) -> None:
    """
    Adapter target for registry.handlers.create (Item).
    Row dict already contains resolved IDs for item_group_id, base_uom_id, brand_id.
    """
    ctx = _ctx_from_row(row)
    repo = InventoryRepository(db.session)
    svc = InventoryService(repo=repo, session=db.session)

    # Only allow exact fields your schema expects
    payload_fields = {
        "name", "description", "item_group_id", "base_uom_id", "brand_id",
        "item_type", "sku", "is_fixed_asset", "asset_category_id"
    }
    data = {k: row[k] for k in payload_fields if k in row}

    # Force fixed-asset off for import flow (as per your policy)
    data.pop("is_fixed_asset", None)
    data.pop("asset_category_id", None)

    payload = ItemCreate(**data)
    svc.create_item(payload, ctx)  # will auto-generate SKU if not provided


def update_item_by_id(row: Dict[str, Any]) -> None:
    """
    Adapter for registry.handlers.update_by.id
    """
    if "id" not in row:
        raise BadRequest("Missing 'id' for update.")

    ctx = _ctx_from_row(row)
    repo = InventoryRepository(db.session)
    svc = InventoryService(repo=repo, session=db.session)

    allowed = {
        "name", "description", "item_group_id", "base_uom_id", "brand_id",
        "item_type"  # you may restrict changing item_type if needed
    }
    data = {k: row[k] for k in allowed if k in row}
    payload = ItemUpdate(**data)

    svc.update_item(int(row["id"]), payload, ctx)


def update_item_by_sku(row: Dict[str, Any]) -> None:
    """
    Fallback adapter when identity is configured to 'sku'.
    """
    sku = (row.get("sku") or "").strip()
    if not sku:
        raise BadRequest("Missing 'sku' for update_by 'sku'.")

    ctx = _ctx_from_row(row)
    repo = InventoryRepository(db.session)
    svc = InventoryService(repo=repo, session=db.session)

    # Look up the item in the same company.
    item = repo.get_item_by_sku(ctx.company_id, sku)
    if not item:
        raise NotFound("Item not found for given SKU.")

    allowed = {
        "name", "description", "item_group_id", "base_uom_id", "brand_id",
        "item_type"
    }
    data = {k: row[k] for k in allowed if k in row}
    payload = ItemUpdate(**data)

    svc.update_item(int(item.id), payload, ctx)
