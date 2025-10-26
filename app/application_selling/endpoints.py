from __future__ import annotations
from flask import Blueprint, request, g
from pydantic import ValidationError

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

bp = Blueprint("selling", __name__, url_prefix="/api/v1/selling")

def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx: raise PermissionError("Authentication context not found.")
    return ctx

# ------------------------- Delivery Note -------------------------

@bp.post("/dn/create")
@require_permission("Sales Delivery Note", "CREATE")
def create_dn():
    try:
        payload = DeliveryNoteCreate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        dn = svc.create_delivery_note(payload=payload, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note created.", 201)
    except ValidationError as e: return api_error(str(e), 422)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

@bp.post("/dn/<int:dn_id>/update")
@require_permission("Sales Delivery Note", "EDIT")
def update_dn(dn_id: int):
    try:
        payload = DeliveryNoteUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        dn = svc.update_delivery_note(dn_id=dn_id, payload=payload, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note updated.", 200)
    except ValidationError as e: return api_error(str(e), 422)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

@bp.post("/dn/<int:dn_id>/submit")
@require_permission("Sales Delivery Note", "SUBMIT")
def submit_dn(dn_id: int):
    try:
        svc = SalesService()
        dn = svc.submit_delivery_note(dn_id=dn_id, context=_ctx())
        return api_success({"id": dn.id, "code": dn.code}, "Delivery Note submitted.", 200)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

# ------------------------- Sales Invoice -------------------------

@bp.post("/invoice/create")
@require_permission("Sales Invoice", "CREATE")
def create_si():
    try:
        payload = SalesInvoiceCreate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        si = svc.create_sales_invoice(payload=payload, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice created.", 201)
    except ValidationError as e: return api_error(str(e), 422)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

@bp.post("/invoice/<int:si_id>/update")
@require_permission("Sales Invoice", "EDIT")
def update_si(si_id: int):
    try:
        payload = SalesInvoiceUpdate.model_validate(request.get_json(silent=True) or {})
        svc = SalesService()
        si = svc.update_sales_invoice(si_id=si_id, payload=payload, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice updated.", 200)
    except ValidationError as e: return api_error(str(e), 422)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

@bp.post("/invoice/<int:si_id>/submit")
@require_permission("Sales Invoice", "SUBMIT")
def submit_si(si_id: int):
    try:
        svc = SalesService()
        si = svc.submit_sales_invoice(si_id=si_id, context=_ctx())
        return api_success({"id": si.id, "code": si.code}, "Sales Invoice submitted.", 200)
    except BizValidationError as e: return api_error(str(e), 400)
    except PermissionError: return api_error("Unauthorized", 401)
    except Exception: return api_error("Unexpected error.", 500)

# ------------------------- Credit Note (Return) -------------------------
# (optional endpoints; reuse the create/submit credit note service methods you already have)
