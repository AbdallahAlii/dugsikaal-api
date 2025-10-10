# app/inventory/endpoints.py

from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.application_nventory.schemas import BrandCreate, UOMCreate, ItemCreate, ItemUpdate, UOMConversionCreate, \
    BranchItemPricingCreate, BranchItemPricingUpdate, PriceBatchLookupOut, PriceLookupOut, PriceBatchLookupRequest, \
    PriceLookupRequest
from app.application_nventory.inventory_services import InventoryLogicError, InventoryService
from app.application_nventory.services.pricing_service import get_selling_rate_batch, get_selling_rate_basic
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



@bp.post("/pricing/resolve")
@require_permission("Pricing", "READ")
def resolve_item_price():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = PriceLookupRequest.model_validate(request.get_json())

        result = get_selling_rate_basic(
            company_id=ctx.company_id,
            branch_id=getattr(ctx, "branch_id", None),
            item_id=payload.item_id,
            txn_uom_id=payload.txn_uom_id,
            posting_date=payload.posting_date,
            price_list_id=payload.price_list_id,
            qty=payload.qty,  # may be None
        )

        return api_success(
            message="Price resolved.",
            data=PriceLookupOut(**result).model_dump(exclude_none=True),
            status_code=200,
        )
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)

@bp.post("/pricing/resolve-batch")
@require_permission("Pricing", "READ")
def resolve_item_price_batch():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = PriceBatchLookupRequest.model_validate(request.get_json())

        results = get_selling_rate_batch(
            company_id=ctx.company_id,
            branch_id=getattr(ctx, "branch_id", None),
            items=[{"item_id": it.item_id, "txn_uom_id": it.txn_uom_id, "qty": it.qty} for it in payload.items],
            posting_date=payload.posting_date,
            price_list_id=payload.price_list_id,
        )

        return api_success(
            message="Prices resolved.",
            data=PriceBatchLookupOut(results=[PriceLookupOut(**r) for r in results]).model_dump(exclude_none=True),
            status_code=200,
        )
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)