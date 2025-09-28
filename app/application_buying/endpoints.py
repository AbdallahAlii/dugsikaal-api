# app/application_buying/endpoints.py
from __future__ import annotations
from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest

# Project Imports
from app.application_buying.schemas import (
    PurchaseReceiptCreate, PurchaseReceiptUpdate,
    PurchaseInvoiceCreate,
)
from app.application_buying.services.invoice_service import PurchaseInvoiceService
from app.application_buying.services.receipt_service import PurchaseReceiptService
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

bp = Blueprint("buying", __name__, url_prefix="/api/buying")
import logging
logger = logging.getLogger(__name__)
def _get_context() -> AffiliationContext:
    _ = get_current_user()  # Ensures user is authenticated
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx

# ------------------------- Purchase Receipt -------------------------

@bp.post("/receipt/create")
@require_permission("Purchase Receipt", "CREATE")
def create_purchase_receipt():
    try:
        ctx = _get_context()
        payload = PurchaseReceiptCreate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseReceiptService()
        pr = svc.create_purchase_receipt(payload=payload, context=ctx)
        return api_success(
            data={"id": pr.id, "code": pr.code},
            message="Purchase Receipt created successfully.",
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

@bp.patch("/receipt/<int:receipt_id>")
@require_permission("Purchase Receipt", "EDIT")
def update_purchase_receipt(receipt_id: int):
    try:
        ctx = _get_context()
        payload = PurchaseReceiptUpdate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseReceiptService()
        pr = svc.update_purchase_receipt(receipt_id=receipt_id, payload=payload, context=ctx)
        return api_success(
            data={"id": pr.id, "code": pr.code},
            message="Purchase Receipt updated successfully.",
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

# @bp.post("/receipt/<int:receipt_id>/submit")
# @require_permission("Purchase Receipt", "SUBMIT")
# def submit_purchase_receipt(receipt_id: int):
#     try:
#         ctx = _get_context()
#         svc = PurchaseReceiptService()
#         pr = svc.submit_purchase_receipt(receipt_id=receipt_id, context=ctx)
#         return api_success(
#             data={"id": pr.id, "code": pr.code},
#             message="Purchase Receipt submitted successfully.",
#             status_code=200,
#         )
#
#     except Forbidden as e:
#         return api_error(e.description, status_code=e.code)
#     except BizValidationError as e:
#         return api_error(str(e), status_code=400)
#     except NotFound as e:
#         return api_error(str(e), status_code=404)
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception:
#         return api_error("An unexpected error occurred.", status_code=500)
@bp.post("/receipt/<int:receipt_id>/submit")
@require_permission("Purchase Receipt", "SUBMIT")
def submit_purchase_receipt(receipt_id: int):
    try:
        ctx = _get_context()
        svc = PurchaseReceiptService()
        pr = svc.submit_purchase_receipt(receipt_id=receipt_id, context=ctx)
        return api_success(
            data={"id": pr.id, "code": pr.code},
            message="Purchase Receipt submitted successfully.",
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
    except Exception as e:
        # 🔥 LOG FULL STACK
        logger.exception("Unhandled error submitting Purchase Receipt", extra={"receipt_id": receipt_id})
        # In dev, return the exception message to speed up debugging
        from flask import current_app
        if current_app.debug or current_app.config.get("ENV") == "development":
            return api_error(f"[DEV TRACE] {e}", status_code=500)
        return api_error("An unexpected error occurred.", status_code=500)
@bp.post("/receipt/<int:receipt_id>/cancel")
@require_permission("Purchase Receipt", "CANCEL")
def cancel_purchase_receipt(receipt_id: int):
    try:
        ctx = _get_context()
        svc = PurchaseReceiptService()
        pr = svc.cancel_purchase_receipt(receipt_id=receipt_id, context=ctx)
        return api_success(
            data={"id": pr.id, "code": pr.code},
            message="Purchase Receipt cancelled successfully.",
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
        return api_error("An unexpected error occurred.", status_code=500)

# ------------------------- Purchase Invoice -------------------------

@bp.post("/invoice/create")
@require_permission("Purchase Invoice", "CREATE")
def create_purchase_invoice():
    try:
        ctx = _get_context()
        payload = PurchaseInvoiceCreate.model_validate(request.get_json(silent=True) or {})
        svc = PurchaseInvoiceService()
        pi = svc.create_purchase_invoice(payload=payload, context=ctx)
        return api_success(
            data={"id": pi.id, "code": pi.code},
            message="Purchase Invoice created successfully.",
            status_code=201,
        )

    except ValidationError as e:
        return api_error(str(e), status_code=422)
    except Forbidden as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=400)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("An unexpected server error occurred.", status_code=500)

@bp.post("/invoice/<int:invoice_id>/submit")
@require_permission("Purchase Invoice", "SUBMIT")
def submit_purchase_invoice(invoice_id: int):
    try:
        ctx = _get_context()
        svc = PurchaseInvoiceService()
        pi = svc.submit_purchase_invoice(invoice_id=invoice_id, context=ctx)
        return api_success(
            data={"id": pi.id, "code": pi.code},
            message="Purchase Invoice submitted successfully.",
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
        return api_error("An unexpected server error occurred.", status_code=500)

@bp.post("/invoice/<int:invoice_id>/cancel")
@require_permission("Purchase Invoice", "CANCEL")
def cancel_purchase_invoice(invoice_id: int):
    try:
        ctx = _get_context()
        svc = PurchaseInvoiceService()
        pi = svc.cancel_purchase_invoice(invoice_id=invoice_id, context=ctx)
        return api_success(
            data={"id": pi.id, "code": pi.code},
            message="Purchase Invoice cancelled successfully.",
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
        return api_error("An unexpected server error occurred.", status_code=500)
