# app/inventory/endpoints.py
from werkzeug.exceptions import BadRequest, Forbidden, NotFound
from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.application_nventory.schemas.inventory_schemas import BrandCreate, UOMCreate, ItemCreate, ItemUpdate, UOMConversionCreate, \
    BranchItemPricingCreate, BranchItemPricingUpdate, PriceBatchLookupOut, PriceLookupOut, PriceBatchLookupRequest, \
    PriceLookupRequest, GenericBulkDelete
from app.application_nventory.inventory_services import InventoryLogicError, InventoryService, DuplicateRecordError
from app.application_nventory.schemas.item_group_schemas import ItemGroupCreate, ItemGroupUpdate
from app.application_nventory.schemas.pricing_schemas import PriceListCreate, ItemPriceUpdate, ItemPriceCreate, \
    PriceListUpdate
from app.application_nventory.services.item_group_service import ItemGroupService
from app.application_nventory.services.item_pricing_services import PricingAdminService
from app.application_nventory.services.pricing_service import get_selling_rate_batch, get_selling_rate_basic
from app.business_validation.error_handling import format_validation_error
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission, check_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user


bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")
svc = InventoryService()

svc_pricing = PricingAdminService()
svc_groups = ItemGroupService()
def _get_ctx():
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx

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


@bp.post("/bulk-delete")
def bulk_delete_generic():
    try:
        ctx = _get_ctx()
        payload = GenericBulkDelete.model_validate(request.get_json(silent=True) or {})

        # permission (dynamic): must match your RBAC doctype names
        check_permission(ctx, payload.doctype, "DELETE")

        out = svc.delete_document_bulk(doctype=payload.doctype, ids=payload.ids, context=ctx)
        return api_success(message="Success", data=out, status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)

    except Forbidden as e:
        return api_error(getattr(e, "description", str(e)), status_code=403)

    except HTTPException as e:
        # if anything bubbles up, keep message clean
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))

    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)


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





@bp.post("/item-groups/create")
@require_permission("Item Group", "CREATE")
def create_item_group():
    ctx = _get_ctx()
    payload = ItemGroupCreate.model_validate(request.get_json(silent=True) or {})
    ok, msg, ig = svc_groups.create_item_group(payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=422)
    return api_success(message=msg, data={"code": ig.code, "name": ig.name}, status_code=201)


@bp.put("/item-groups/<int:item_group_id>/update")
@require_permission("Item Group", "UPDATE")
def update_item_group(item_group_id: int):
    ctx = _get_ctx()
    payload = ItemGroupUpdate.model_validate(request.get_json(silent=True) or {})
    ok, msg, ig = svc_groups.update_item_group(item_group_id=item_group_id, payload=payload, context=ctx)
    if not ok:
        return api_error(msg, status_code=422)
    return api_success(message=msg, data={"code": ig.code, "name": ig.name}, status_code=200)



@bp.post("/items/create")
@require_permission("Item", "CREATE")
def create_item():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = ItemCreate.model_validate(request.get_json())
        result = svc.create_item(payload, ctx)

        # ⬇️ Return ONLY a friendly message and the item name (no other fields)
        return api_success(
            message="Item created successfully.",
            data={"name": result.name},
            status_code=201,
        )

    except ValidationError as e:
        clean_message = format_validation_error(e)
        return api_error(clean_message, status_code=422)
    except (InventoryLogicError, DuplicateRecordError) as e:
        return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.put("/items/<int:item_id>")
@require_permission("Item", "UPDATE")
def update_item(item_id: int):
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = ItemUpdate.model_validate(request.get_json())
        result = svc.update_item(item_id, payload, ctx)
        return api_success(message="Item updated successfully.", data={"name": result.name}, status_code=200)
    except ValidationError as e:
        # ✅ show short, clean messages
        return api_error(format_validation_error(e), status_code=422)
    except (InventoryLogicError, DuplicateRecordError) as e:
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



# ------------------------- Price List -------------------------
@bp.post("/price-lists/create")
@require_permission("Price List", "CREATE")
def create_price_list():
    try:
        ctx = _get_ctx()
        payload = PriceListCreate.model_validate(request.get_json(silent=True) or {})
        pl = svc_pricing.create_price_list(payload, ctx)
        # ⬇️ short ERP-style success: only message + name
        return api_success(message="Price List created.", data={"name": pl.name}, status_code=201)
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/price-lists/<int:price_list_id>/update")
@require_permission("Price List", "UPDATE")
def update_price_list(price_list_id: int):
    try:
        ctx = _get_ctx()
        payload = PriceListUpdate.model_validate(request.get_json(silent=True) or {})
        pl = svc_pricing.update_price_list(price_list_id, payload, ctx)
        # ⬇️ short ERP-style success: only message + name
        return api_success(message="Price List updated.", data={"name": pl.name}, status_code=200)
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)


# ------------------------- Item Price -------------------------



@bp.post("/item-prices/create")
@require_permission("Item Price", "CREATE")
def create_item_price():
    try:
        ctx = _get_ctx()
        payload = ItemPriceCreate.model_validate(request.get_json(silent=True) or {})
        ip = svc_pricing.create_item_price(payload, ctx)
        # ⬇️ short ERP-style success: only message + code
        return api_success(message="Item Price created.", data={"code": ip.code}, status_code=201)
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/item-prices/<int:item_price_id>/update")
@require_permission("Item Price", "UPDATE")
def update_item_price(item_price_id: int):
    try:
        ctx = _get_ctx()
        payload = ItemPriceUpdate.model_validate(request.get_json(silent=True) or {})
        ip = svc_pricing.update_item_price(item_price_id, payload, ctx)
        # ⬇️ short ERP-style success: only message + code
        return api_success(message="Item Price updated.", data={"code": ip.code}, status_code=200)
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)