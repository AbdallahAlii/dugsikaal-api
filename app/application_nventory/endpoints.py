# app/inventory/endpoints.py

from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.application_nventory.schemas import BrandCreate, UOMCreate, ItemCreate, ItemUpdate, UOMConversionCreate, \
    BranchItemPricingCreate, BranchItemPricingUpdate
from app.application_nventory.services import InventoryLogicError, InventoryService
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user


bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")
svc = InventoryService()


@bp.post("/brands/create")
@require_permission("Brand", "CREATE")
def create_brand():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = BrandCreate.model_validate(request.get_json())
        svc.create_brand(payload, ctx)
        return api_success(message="Brand created successfully.", data={}, status_code=201)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.post("/uoms/create")
@require_permission("UOM", "CREATE")
def create_uom():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = UOMCreate.model_validate(request.get_json())
        svc.create_uom(payload, ctx)
        return api_success(message="UOM created successfully.", data={}, status_code=201)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.post("/items/create")
@require_permission("Item", "CREATE")
def create_item():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = ItemCreate.model_validate(request.get_json())
        svc.create_item(payload, ctx)
        return api_success(message="Item created successfully.", data={}, status_code=201)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.put("/update/items/<int:item_id>")
@require_permission("Item", "UPDATE")
def update_item(item_id: int):
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = ItemUpdate.model_validate(request.get_json())
        svc.update_item(item_id, payload, ctx)
        return api_success(message="Item updated successfully.", data={}, status_code=200)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.post("/uom-conversions/create")
@require_permission("UOM Conversion", "CREATE")
def create_uom_conversion():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = UOMConversionCreate.model_validate(request.get_json())
        svc.create_uom_conversion(payload, ctx)
        return api_success(message="UOM Conversion created successfully.", data={}, status_code=201)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.post("/pricing/create")
@require_permission("Item Price", "CREATE")
def create_pricing():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = BranchItemPricingCreate.model_validate(request.get_json())
        svc.create_branch_item_pricing(payload, ctx)
        return api_success(message="Pricing created successfully.", data={}, status_code=201)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.put("/update/pricing/<int:pricing_id>")
@require_permission("Item Price", "UPDATE")
def update_pricing(pricing_id: int):
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = BranchItemPricingUpdate.model_validate(request.get_json())
        svc.update_branch_item_pricing(pricing_id, payload, ctx)
        return api_success(message="Pricing updated successfully.", data={}, status_code=200)
    except (InventoryLogicError, ValidationError) as e:
        if isinstance(e, InventoryLogicError):
            return api_error(e.description, status_code=422)
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)