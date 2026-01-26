from __future__ import annotations

import datetime
import logging
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Forbidden, Conflict, BadRequest, HTTPException

from app.application_stock.schemas.reconciliation_schemas import StockReconciliationCreate, StockReconciliationUpdate
# Warehouse bits
from app.application_stock.schemas.warehouse_schemas import WarehouseCreate, WarehouseUpdate, WarehouseOut, IdCode, \
    WarehouseBulkDelete
from app.application_stock.services.availability_service import StockAvailabilityService
from app.application_stock.services.reconciliation_service import StockReconciliationService
from app.application_stock.services.warehouse_service import WarehouseService
from app.application_stock.helpers.warehouse_validation import WarehouseRuleError

# Stock Entry bits
from app.application_stock.schemas.stock_entry_schemas import StockEntryCreate, StockEntryUpdate
from app.application_stock.services.stock_entry_service import StockEntryService

from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

bp = Blueprint("stock", __name__, url_prefix="/api/stock")
logger = logging.getLogger(__name__)


def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx


# ------------------------- Warehouses -------------------------

@bp.post("/warehouses/create")
@require_permission("Warehouse", "CREATE")
def create_warehouse():
    try:
        ctx = _ctx()
        payload = WarehouseCreate.model_validate(request.get_json(silent=True) or {})
        svc = WarehouseService()
        wh = svc.create_warehouse(payload=payload, context=ctx)
        return api_success(data=IdCode(id=wh.id, code=wh.code).model_dump(), status_code=201)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except WarehouseRuleError as e:
        return api_error(str(e), status_code=400)
    except HTTPException as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)


@bp.patch("/warehouses/<int:warehouse_id>/update")
@require_permission("Warehouse", "UPDATE")
def update_warehouse(warehouse_id: int):
    try:
        ctx = _ctx()
        payload = WarehouseUpdate.model_validate(request.get_json(silent=True) or {})
        svc = WarehouseService()
        wh = svc.update_warehouse(warehouse_id=warehouse_id, payload=payload, context=ctx)
        return api_success(data=IdCode(id=wh.id, code=wh.code).model_dump(), status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except WarehouseRuleError as e:
        return api_error(str(e), status_code=400)
    except HTTPException as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)


@bp.delete("/warehouses/<int:warehouse_id>/delete")
@require_permission("Warehouse", "DELETE")
def delete_warehouse(warehouse_id: int):
    try:
        ctx = _ctx()
        svc = WarehouseService()
        svc.delete_warehouse(warehouse_id=warehouse_id, context=ctx)
        return api_success(data={"id": warehouse_id}, status_code=200)

    except WarehouseRuleError as e:
        return api_error(str(e), status_code=400)
    except HTTPException as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)
@bp.post("/warehouses/bulk-delete")
@require_permission("Warehouse", "DELETE")
def bulk_delete_warehouses():
    try:
        ctx = _ctx()
        payload = WarehouseBulkDelete.model_validate(request.get_json(silent=True) or {})
        svc = WarehouseService()
        out = svc.delete_warehouses_bulk(warehouse_ids=payload.ids, context=ctx)
        return api_success(data=out, status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except WarehouseRuleError as e:
        return api_error(str(e), status_code=400)
    except HTTPException as e:
        return api_error(getattr(e, "description", str(e)), status_code=getattr(e, "code", 400))
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)


# ------------------------- Stock Entry -------------------------


@bp.post("/stock_entry/create")
@require_permission("Stock Entry", "CREATE")
def create_stock_entry():
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}
        payload = StockEntryCreate.model_validate(raw)
        svc = StockEntryService()
        se = svc.create_stock_entry(payload=payload, context=ctx)
        return api_success(
            data={"id": se.id, "code": se.code},
            message="Stock Entry created successfully.",
            status_code=201,
        )
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception(
            "Unhandled error creating Stock Entry",
            extra={"route": "stock.entry.create", "request_json": raw},
        )
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e.__class__.__name__}: {e}", status_code=500)
        return api_error("An unexpected server error occurred.", status_code=500)


@bp.patch("/stock_entry/<int:entry_id>")
@require_permission("Stock Entry", "EDIT")
def update_stock_entry(entry_id: int):
    try:
        ctx = _ctx()
        payload = StockEntryUpdate.model_validate(request.get_json(silent=True) or {})
        svc = StockEntryService()
        se = svc.update_stock_entry(se_id=entry_id, payload=payload, context=ctx)
        return api_success(
            data={"id": se.id, "code": se.code},
            message="Stock Entry updated successfully.",
            status_code=200,
        )
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except Forbidden as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=400)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/stock_entry/<int:entry_id>/submit")
@require_permission("Stock Entry", "SUBMIT")
def submit_stock_entry(entry_id: int):
    try:
        ctx = _ctx()
        svc = StockEntryService()
        se = svc.submit_stock_entry(se_id=entry_id, context=ctx)
        return api_success(
            data={"id": se.id, "code": se.code},
            message="Stock Entry submitted successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(
            e.description if hasattr(e, "description") else str(e),
            status_code=getattr(e, "code", 400),
        )
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception(
            "Unhandled error submitting Stock Entry", extra={"entry_id": entry_id}
        )
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/stock_entry/<int:entry_id>/cancel")
@require_permission("Stock Entry", "CANCEL")
def cancel_stock_entry(entry_id: int):
    try:
        ctx = _ctx()
        svc = StockEntryService()
        se = svc.cancel_stock_entry(se_id=entry_id, context=ctx)
        return api_success(
            data={"id": se.id, "code": se.code},
            message="Stock Entry cancelled successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(
            e.description if hasattr(e, "description") else str(e),
            status_code=getattr(e, "code", 400),
        )
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)




@bp.post("/reconciliation/create")
@require_permission("Stock Reconciliation", "CREATE")
def create_stock_reconciliation():
    try:
        ctx = _ctx()
        payload = StockReconciliationCreate.model_validate(
            request.get_json(silent=True) or {}
        )
        svc = StockReconciliationService()
        recon = svc.create_stock_reconciliation(
            payload=payload.model_dump(), context=ctx
        )

        return api_success(
            data={"id": recon.id, "code": recon.code},
            message="Stock Reconciliation created in Draft status.",
            status_code=201,
        )
    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        logger.exception("Unexpected error creating Stock Reconciliation")
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/reconciliation/Update/<int:recon_id>")
@require_permission("Stock Reconciliation", "EDIT")
def update_stock_reconciliation(recon_id: int):
    """Update a Draft stock reconciliation (header + lines)."""
    try:
        ctx = _ctx()
        payload = StockReconciliationUpdate.model_validate(
            request.get_json(silent=True) or {}
        )

        svc = StockReconciliationService()
        # exclude_unset=True so we don't overwrite with None
        recon = svc.update_stock_reconciliation(
            recon_id=recon_id,
            payload=payload.model_dump(exclude_unset=True),
            context=ctx,
        )

        return api_success(
            data={"id": recon.id, "code": recon.code},
            message="Stock Reconciliation updated.",
            status_code=200,
        )

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except Forbidden as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        logger.exception(
            "Unhandled error updating Stock Reconciliation",
            extra={"recon_id": recon_id},
        )
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/reconciliation/<int:recon_id>/submit")
@require_permission("Stock Reconciliation", "SUBMIT")
def submit_stock_reconciliation(recon_id: int):
    try:
        ctx = _ctx()
        svc = StockReconciliationService()
        recon = svc.submit_stock_reconciliation(recon_id=recon_id, context=ctx)

        return api_success(
            data={"id": recon.id, "code": recon.code},
            message="Stock Reconciliation submitted successfully.",
            status_code=200,
        )
    except Forbidden as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        logger.exception(
            "Unhandled error submitting Stock Reconciliation",
            extra={"recon_id": recon_id},
        )
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/reconciliation/<int:recon_id>/cancel")
@require_permission("Stock Reconciliation", "CANCEL")
def cancel_stock_reconciliation(recon_id: int):
    """Cancel a submitted stock reconciliation."""
    try:
        ctx = _ctx()
        svc = StockReconciliationService()
        recon = svc.cancel_stock_reconciliation(recon_id=recon_id, context=ctx)

        return api_success(
            data={"id": recon.id, "code": recon.code},
            message="Stock Reconciliation cancelled successfully.",
            status_code=200,
        )

    except Forbidden as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        logger.exception(
            "Unhandled error cancelling Stock Reconciliation",
            extra={"recon_id": recon_id},
        )
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/availability")
@require_permission("Item", "READ")
def availability():
    """
    POST /api/stock/availability

    Single:
    {
      "item_id": 28,
      "warehouse_ids": [4],   // one or many leaf warehouses
      "uom_id": 3,            // optional; only affects 'available_txn' in detail mode
      "detail": false,        // default false (returns only 'available' in Stock UOM)
      "at": null              // optional ISO8601 (as-of)
    }

    Batch:
    {
      "lines": [
        {"row_id": "r1", "item_id": 28, "warehouse_ids": [4], "uom_id": 3},
        {"row_id": "r2", "item_id": 31, "warehouse_ids": [7]}
      ],
      "detail": true,
      "at": "2025-10-31T12:00:00Z"
    }
    """
    try:
        ctx = _ctx()
        raw = request.get_json(silent=True) or {}
        detail = bool(raw.get("detail", False))
        at_raw = raw.get("at")
        at_dt = datetime.fromisoformat(at_raw) if at_raw else None

        svc = StockAvailabilityService()

        if isinstance(raw.get("lines"), list):
            data = svc.compute_batch(context=ctx, lines=raw["lines"], at=at_dt, detail=detail)
            return api_success({"lines": data})

        # single
        item_id = int(raw["item_id"])
        data = svc.compute_single(
            context=ctx,
            item_id=item_id,
            warehouse_ids=raw.get("warehouse_ids") or [],
            uom_id=raw.get("uom_id"),
            at=at_dt,
            detail=detail,
        )
        return api_success(data)

    except Exception as e:
        return api_error(str(e), status_code=400)