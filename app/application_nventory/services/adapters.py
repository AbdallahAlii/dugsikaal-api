
# app/application_nventory/services/adapters.py
from __future__ import annotations
from typing import Any, Dict

from werkzeug.exceptions import BadRequest, NotFound

from app.application_nventory.inventory_services import InventoryService
from app.security.rbac_effective import AffiliationContext
from app.application_nventory.schemas.inventory_schemas import ItemCreate, ItemUpdate
from app.application_nventory.repo.inventory_repo import InventoryRepository
from config.database import db


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build a context for the importer.

    IMPORTANT:
    - company_id and branch_id come from the DataImport row (injected in pipeline._inject_context)
    - We mark this context as effectively "system-level" for that company so that
      ensure_scope_by_ids does NOT reject it as out-of-scope.

    HTTP /api/data-imports endpoints already enforced permission via
    @require_permission("Data Import", ...).
    """

    company_id = int(row.get("company_id") or 0)
    branch_id_raw = row.get("branch_id")
    branch_id = int(branch_id_raw) if branch_id_raw is not None else None

    user_id_raw = row.get("created_by_id")
    user_id = int(user_id_raw) if user_id_raw is not None else 0

    # -------- Roles --------
    raw_roles = row.get("roles")
    if isinstance(raw_roles, (list, set, tuple)):
        roles = set(raw_roles)
    elif isinstance(raw_roles, str) and raw_roles.strip():
        roles = {r.strip() for r in raw_roles.split(",") if r.strip()}
    else:
        # No default "master-data" role; imports don't rely on roles anymore
        roles = set()

    # -------- Affiliations --------
    affiliations: list = []

    # -------- Permissions --------
    raw_permissions = row.get("permissions")
    if isinstance(raw_permissions, (list, set, tuple)):
        permissions = set(raw_permissions)
    elif isinstance(raw_permissions, str) and raw_permissions.strip():
        permissions = {p.strip() for p in raw_permissions.split(",") if p.strip()}
    else:
        permissions = set()

    is_system_admin = True
    user_type = row.get("user_type") or "user"

    return AffiliationContext(
        user_id=user_id,
        user_type=user_type,
        company_id=company_id,
        branch_id=branch_id,
        roles=roles,
        affiliations=affiliations,
        permissions=permissions,
        is_system_admin=is_system_admin,
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
        "name",
        "description",
        "item_group_id",
        "base_uom_id",
        "brand_id",
        "item_type",
        "sku",
        "is_fixed_asset",
        "asset_category_id",
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
        "name",
        "description",
        "item_group_id",
        "base_uom_id",
        "brand_id",
        "item_type",  # you may restrict changing item_type if needed
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
        "name",
        "description",
        "item_group_id",
        "base_uom_id",
        "brand_id",
        "item_type",
    }
    data = {k: row[k] for k in allowed if k in row}
    payload = ItemUpdate(**data)

    svc.update_item(int(item.id), payload, ctx)
