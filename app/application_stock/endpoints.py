from __future__ import annotations

import logging
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Forbidden, Conflict, BadRequest, HTTPException

# Warehouse bits
from app.application_stock.schemas.warehouse_schemas import WarehouseCreate, WarehouseUpdate, WarehouseOut, IdCode
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


@bp.delete("/warehouses/<int:warehouse_id>")
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


# ------------------------- Stock Entry -------------------------

@bp.post("/entry/create")
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
        logger.exception("Unhandled error creating Stock Entry", extra={"route": "stock.entry.create", "request_json": raw})
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e.__class__.__name__}: {e}", status_code=500)
        return api_error("An unexpected server error occurred.", status_code=500)


@bp.patch("/entry/<int:entry_id>")
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


@bp.post("/entry/<int:entry_id>/submit")
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
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Stock Entry", extra={"entry_id": entry_id})
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/entry/<int:entry_id>/cancel")
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
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)
