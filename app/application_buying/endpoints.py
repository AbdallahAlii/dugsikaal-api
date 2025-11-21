# app/application_buying/endpoints.py
from __future__ import annotations

import logging
from flask import Blueprint, request, g, current_app
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest

from app.application_buying.schemas import (
    PurchaseReceiptCreate, PurchaseReceiptUpdate,
    PurchaseInvoiceCreate, PurchaseInvoiceUpdate,
)
from app.application_buying.services.receipt_service import PurchaseReceiptService
from app.application_buying.services.invoice_service import PurchaseInvoiceService
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

from app.business_validation import item_validation as V
logger = logging.getLogger(__name__)

bp = Blueprint("buying", __name__, url_prefix="/api/buying")


def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# Purchase Receipts
# ──────────────────────────────────────────────────────────────────────────────

@bp.post("/receipt/create")
@require_permission("Purchase Receipt", "CREATE")
def create_purchase_receipt():
    try:
        payload = PurchaseReceiptCreate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseReceiptService()
        pr = svc.create_purchase_receipt(payload=payload, context=_ctx())
        return api_success({"id": pr.id, "code": pr.code}, "Purchase Receipt created (Draft).", status_code=201)

    except ValidationError as e:
        logger.error("ValidationError (PR create): %s", str(e))
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        msg = e.description if hasattr(e, "description") else str(e)
        logger.error("HTTP error (PR create): %s", msg)
        return api_error(msg, status_code=e.code)
    except BizValidationError as e:
        logger.error("BizValidationError (PR create): %s", str(e))
        return api_error(str(e), status_code=400)
    except PermissionError:
        logger.error("PermissionError (PR create): Unauthorized")
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error creating Purchase Receipt")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/receipt/<int:receipt_id>/submit")
@require_permission("Purchase Receipt", "SUBMIT")
def submit_purchase_receipt(receipt_id: int):
    try:
        svc = PurchaseReceiptService()
        pr = svc.submit_purchase_receipt(receipt_id=receipt_id, context=_ctx())
        return api_success({"id": pr.id, "code": pr.code}, "Purchase Receipt submitted.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Purchase Receipt")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/receipt/<int:receipt_id>/cancel")
@require_permission("Purchase Receipt", "CANCEL")
def cancel_purchase_receipt(receipt_id: int):
    try:
        svc = PurchaseReceiptService()
        pr = svc.cancel_purchase_receipt(receipt_id=receipt_id, context=_ctx())
        return api_success({"id": pr.id, "code": pr.code}, "Purchase Receipt cancelled.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error cancelling Purchase Receipt")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


# ──────────────────────────────────────────────────────────────────────────────
# Purchase Invoices
# ──────────────────────────────────────────────────────────────────────────────

@bp.post("/invoice/create")
@require_permission("Purchase Invoice", "CREATE")
def create_purchase_invoice():
    try:
        payload = PurchaseInvoiceCreate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseInvoiceService()
        pi = svc.create_purchase_invoice(payload=payload, context=_ctx())
        return api_success({"id": pi.id, "code": pi.code}, "Purchase Invoice created (Draft).", status_code=201)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        msg = e.description if hasattr(e, "description") else str(e)
        return api_error(msg, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error creating Purchase Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.patch("/invoice/<int:invoice_id>/update")
@require_permission("Purchase Invoice", "UPDATE")
def update_purchase_invoice(invoice_id: int):
    try:
        payload = PurchaseInvoiceUpdate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseInvoiceService()
        pi = svc.update_purchase_invoice(invoice_id=invoice_id, payload=payload, context=_ctx())
        return api_success({"id": pi.id, "code": pi.code}, "Purchase Invoice updated.", status_code=200)

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error updating Purchase Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)
@bp.get("/invoice/<int:invoice_id>/make-return-template")
@require_permission("Purchase Invoice", "CREATE")
def make_purchase_invoice_return_template(invoice_id: int):
    """
    Build a mapped RETURN template for given Purchase Invoice ID.
    Used by UI to pre-fill the Purchase Invoice Create form (debit note).
    """
    try:
        svc = PurchaseInvoiceService()
        tmpl = svc.build_purchase_invoice_return_template(
            original_pi_id=invoice_id,
            context=_ctx(),
        )
        return api_success(tmpl, "Purchase Invoice return template built.")

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        msg = e.description if hasattr(e, "description") else str(e)
        return api_error(msg, status_code=e.code)
    except V.BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error building Purchase Invoice return template")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/invoice/<int:invoice_id>/submit")
@require_permission("Purchase Invoice", "SUBMIT")
def submit_purchase_invoice(invoice_id: int):
    try:
        svc = PurchaseInvoiceService()
        pi = svc.submit_purchase_invoice(invoice_id=invoice_id, context=_ctx())
        return api_success({"id": pi.id, "code": pi.code}, "Purchase Invoice submitted.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error submitting Purchase Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)


@bp.post("/invoice/<int:invoice_id>/cancel")
@require_permission("Purchase Invoice", "CANCEL")
def cancel_purchase_invoice(invoice_id: int):
    try:
        svc = PurchaseInvoiceService()
        pi = svc.cancel_purchase_invoice(invoice_id=invoice_id, context=_ctx())
        return api_success({"id": pi.id, "code": pi.code}, "Purchase Invoice cancelled.", status_code=200)

    except (Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unhandled error cancelling Purchase Invoice")
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("Unexpected error.", status_code=500)
