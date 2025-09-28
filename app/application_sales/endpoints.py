# app/api/v1/sales/endpoints.py

from __future__ import annotations
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest
import logging

# Project Imports
from app.application_sales.schemas import (
    SalesQuotationCreate, SalesQuotationUpdate, SalesQuotationActionResponse,
    SalesDeliveryNoteCreate, SalesDeliveryNoteUpdate, SalesDeliveryNoteActionResponse,
    SalesInvoiceCreate, SalesInvoiceUpdate, SalesInvoiceActionResponse
)
from app.application_sales.services.quotation_service import SalesQuotationService
from app.application_sales.services.delivery_note_service import SalesDeliveryNoteService
from app.application_sales.services.invoice_service import SalesInvoiceService
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

bp = Blueprint("sales", __name__, url_prefix="/api/sales")
logger = logging.getLogger(__name__)

def _get_context() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx

# ------------------------- Sales Quotation -------------------------

@bp.post("/quotation/create")
@require_permission("Sales Quotation", "CREATE")
def create_sales_quotation():
    try:
        ctx = _get_context()
        payload = SalesQuotationCreate.model_validate(request.get_json(silent=True) or {})
        svc = SalesQuotationService()
        sq = svc.create_sales_quotation(payload=payload, context=ctx)
        return api_success(
            data={"id": sq.id, "code": sq.code},
            message="Sales Quotation created successfully.",
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
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)

@bp.patch("/quotation/<int:quotation_id>")
@require_permission("Sales Quotation", "EDIT")
def update_sales_quotation(quotation_id: int):
    try:
        ctx = _get_context()
        payload = SalesQuotationUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesQuotationService()
        sq = svc.update_sales_quotation(quotation_id=quotation_id, payload=payload, context=ctx)
        return api_success(
            data={"id": sq.id, "code": sq.code},
            message="Sales Quotation updated successfully.",
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

@bp.post("/quotation/<int:quotation_id>/submit")
@require_permission("Sales Quotation", "SUBMIT")
def submit_sales_quotation(quotation_id: int):
    try:
        ctx = _get_context()
        svc = SalesQuotationService()
        sq = svc.submit_sales_quotation(quotation_id=quotation_id, context=ctx)
        return api_success(
            data={"id": sq.id, "code": sq.code},
            message="Sales Quotation submitted successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(e.description, status_code=e.code)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)

@bp.post("/quotation/<int:quotation_id>/cancel")
@require_permission("Sales Quotation", "CANCEL")
def cancel_sales_quotation(quotation_id: int):
    try:
        ctx = _get_context()
        svc = SalesQuotationService()
        sq = svc.cancel_sales_quotation(quotation_id=quotation_id, context=ctx)
        return api_success(
            data={"id": sq.id, "code": sq.code},
            message="Sales Quotation cancelled successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(e.description, status_code=e.code)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)

# ------------------------- Sales Delivery Note -------------------------

@bp.post("/delivery_note/create")
@require_permission("Delivery Note", "CREATE")
def create_sales_delivery_note():
    try:
        ctx = _get_context()
        raw = request.get_json(silent=True) or {}
        payload = SalesDeliveryNoteCreate.model_validate(raw)
        svc = SalesDeliveryNoteService()
        sdn = svc.create_sales_delivery_note(payload=payload, context=ctx)
        return api_success(
            data={"id": sdn.id, "code": sdn.code},
            message="Sales Delivery Note created successfully.",
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
        # Add detailed logging for unhandled exceptions
        logger.exception("Unhandled error creating Sales Delivery Note", extra={
            "route": "sales.delivery_note.create",
            "request_json": raw, # Use 'raw' here to log the raw JSON body
        })
        # Provide more details in development environment
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e.__class__.__name__}: {e}", status_code=500)
        return api_error("An unexpected server error occurred.", status_code=500)

@bp.patch("/delivery_note/<int:delivery_note_id>")
@require_permission("Delivery Note", "EDIT")
def update_sales_delivery_note(delivery_note_id: int):
    try:
        ctx = _get_context()
        payload = SalesDeliveryNoteUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesDeliveryNoteService()
        sdn = svc.update_sales_delivery_note(sdn_id=delivery_note_id, payload=payload, context=ctx)
        return api_success(
            data={"id": sdn.id, "code": sdn.code},
            message="Sales Delivery Note updated successfully.",
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

@bp.post("/delivery_note/<int:delivery_note_id>/submit")
@require_permission("Delivery Note", "SUBMIT")
def submit_sales_delivery_note(delivery_note_id: int):
    try:
        ctx = _get_context()
        svc = SalesDeliveryNoteService()
        sdn = svc.submit_sales_delivery_note(sdn_id=delivery_note_id, context=ctx)
        return api_success(
            data={"id": sdn.id, "code": sdn.code},
            message="Sales Delivery Note submitted successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(e.description, status_code=e.code)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Sales Delivery Note", extra={"sdn_id": delivery_note_id})
        from flask import current_app
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("An unexpected error occurred.", status_code=500)

@bp.post("/delivery_note/<int:delivery_note_id>/cancel")
@require_permission("Delivery Note", "CANCEL")
def cancel_sales_delivery_note(delivery_note_id: int):
    try:
        ctx = _get_context()
        svc = SalesDeliveryNoteService()
        sdn = svc.cancel_sales_delivery_note(sdn_id=delivery_note_id, context=ctx)
        return api_success(
            data={"id": sdn.id, "code": sdn.code},
            message="Sales Delivery Note cancelled successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(e.description, status_code=e.code)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected error occurred.", status_code=500)

# ------------------------- Sales Invoice -------------------------

@bp.post("/invoice/create")
@require_permission("Sales Invoice", "CREATE")
def create_sales_invoice():
    try:
        ctx = _get_context()
        raw = request.get_json(silent=True) or {}
        payload = SalesInvoiceCreate.model_validate(raw)
        svc = SalesInvoiceService()
        si = svc.create_sales_invoice(payload=payload, context=ctx)
        return api_success(
            data={"id": si.id, "code": si.code},
            message="Sales Invoice created successfully.",
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
        # 🔥 Show us what's actually blowing up
        logger.exception("Unhandled error creating Sales Invoice", extra={
            "route": "sales.invoice.create",
            "request_json": request.get_json(silent=True),
        })
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e.__class__.__name__}: {e}", status_code=500)
        return api_error("An unexpected server error occurred.", status_code=500)

@bp.post("/invoice/<int:invoice_id>/submit")
@require_permission("Sales Invoice", "SUBMIT")
def submit_sales_invoice(invoice_id: int):
    try:
        ctx = _get_context()
        svc = SalesInvoiceService()
        si = svc.submit_sales_invoice(invoice_id=invoice_id, context=ctx)
        return api_success(
            data={"id": si.id, "code": si.code},
            message="Sales Invoice submitted successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound) as e:
        # These are werkzeug exceptions, which have .description and .code
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        # This is a custom exception. It only has a string message.
        return api_error(str(e), status_code=400) # Use 400 for a bad request/state
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)

@bp.post("/invoice/<int:invoice_id>/cancel")
@require_permission("Sales Return", "CANCEL")
def cancel_sales_invoice(invoice_id: int):
    try:
        ctx = _get_context()
        svc = SalesInvoiceService()
        si = svc.cancel_sales_invoice(invoice_id=invoice_id, context=ctx)
        return api_success(
            data={"id": si.id, "code": si.code},
            message="Sales Invoice cancelled successfully.",
            status_code=200,
        )
    except (Forbidden, NotFound, BizValidationError) as e:
        return api_error(e.description, status_code=e.code)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)