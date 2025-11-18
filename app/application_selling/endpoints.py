# app/application_selling/endpoints.py
from __future__ import annotations

import logging
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Forbidden, Conflict, BadRequest

from app.application_selling.schemas import (
    DeliveryNoteCreate, DeliveryNoteUpdate,
    SalesInvoiceCreate, SalesInvoiceUpdate,
    SalesCreditNoteCreate
)
from app.application_selling.services.sales_service import SalesService
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

logger = logging.getLogger(__name__)

bp = Blueprint("selling", __name__, url_prefix="/api/v1/selling")


def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx


# ------------------------- Delivery Note -------------------------

@bp.post("/dn/create")
@require_permission("Sales Delivery Note", "CREATE")
def create_dn():
    try:
        payload = DeliveryNoteCreate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        dn = svc.create_delivery_note(payload=payload, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note created.", status_code=201)

    except ValidationError as e:
        logger.error("ValidationError: %s", str(e))
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        logger.error("HTTP error: %s", e.description if hasattr(e, "description") else str(e))
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=e.code)
    except BizValidationError as e:
        logger.error("BizValidationError: %s", str(e))
        return api_error(str(e), status_code=400)
    except PermissionError:
        logger.error("PermissionError: Unauthorized")
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error: %s", str(e))
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/dn/<int:dn_id>/update")
@require_permission("Sales Delivery Note", "EDIT")
def update_dn(dn_id: int):
    try:
        payload = DeliveryNoteUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        dn = svc.update_delivery_note(dn_id=dn_id, payload=payload, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note updated.", status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error updating DN: %s", str(e))
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/dn/<int:dn_id>/submit")
@require_permission("Sales Delivery Note", "SUBMIT")
def submit_dn(dn_id: int):
    try:
        svc = SalesService()
        dn = svc.submit_delivery_note(dn_id=dn_id, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note submitted.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Delivery Note")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


# ------------------------- Sales Invoice -------------------------

@bp.post("/invoice/create")
@require_permission("Sales Invoice", "CREATE")
def create_si():
    try:
        payload = SalesInvoiceCreate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        si = svc.create_sales_invoice(payload=payload, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice created.", status_code=201)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error creating Sales Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)
@bp.get("/invoice/<int:si_id>/make-return-template")
@require_permission("Sales Invoice", "CREATE")
def make_return_template(si_id: int):
    """
    Build a mapped RETURN template for given Sales Invoice ID.
    Used by UI to pre-fill the Sales Invoice Create form.
    """
    try:
        svc = SalesService()
        tmpl = svc.build_sales_invoice_return_template(
            original_si_id=si_id,
            context=_ctx(),
        )
        return api_success(tmpl, "Return template built.")
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(
            e.description if hasattr(e, "description") else str(e),
            status_code=e.code,
        )
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        current_app.logger.exception("Unexpected error building SI return template")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)

@bp.put("/invoice/<int:si_id>/update")
@require_permission("Sales Invoice", "EDIT")
def update_si(si_id: int):
    try:
        payload = SalesInvoiceUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        si = svc.update_sales_invoice(si_id=si_id, payload=payload, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice updated.", status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error updating Sales Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/invoice/<int:si_id>/submit")
@require_permission("Sales Invoice", "SUBMIT")
def submit_si(si_id: int):
    try:
        svc = SalesService()
        si = svc.submit_sales_invoice(si_id=si_id, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice submitted.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Sales Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)

# Cancel Sales Invoice
@bp.post("/invoice/<int:si_id>/cancel")
@require_permission("Sales Invoice", "CANCEL")
def cancel_si(si_id: int):
    try:
        svc = SalesService()
        si = svc.cancel_sales_invoice(si_id=si_id, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice cancelled.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error cancelling Sales Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)
