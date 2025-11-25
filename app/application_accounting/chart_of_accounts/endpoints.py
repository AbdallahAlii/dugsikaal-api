from __future__ import annotations
from flask import Blueprint, request, g
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest, HTTPException
import logging

from app.application_accounting.chart_of_accounts.schemas.account_policies_schemas import ModeOfPaymentCreate, \
    ModeOfPaymentUpdate, AccountAccessPolicyUpdate, AccountAccessPolicyCreate
from app.application_accounting.chart_of_accounts.schemas.fiscal_year_schemas import (
    FiscalYearCreate,
    FiscalYearUpdate,
)
from app.application_accounting.chart_of_accounts.schemas.journal_schemas import JournalEntryCreateSchema, \
    JournalEntryUpdateSchema, JournalEntrySubmitSchema, JournalEntryCancelSchema
from app.application_accounting.chart_of_accounts.schemas.payment_schemas import ExpenseCreateSchema, \
    ExpenseUpdateSchema, ExpenseCancelSchema, PaymentCreateSchema, PaymentUpdateSchema, PaymentSubmitSchema, \
    PaymentCancelSchema, OutstandingFilter, ExpenseTypeCreate, ExpenseTypeUpdate, ExpenseSubmitSchema
from app.application_accounting.chart_of_accounts.services.account_policy_services import PoliciesService
from app.application_accounting.chart_of_accounts.services.expense_service import ExpenseService
from app.application_accounting.chart_of_accounts.services.fiscal_year_services import (
    FiscalYearService,
)
from app.application_accounting.chart_of_accounts.schemas.pcv_schemas import (
    PCVCreate as PeriodClosingVoucherCreateSchema,
    PCVUpdate as PeriodClosingVoucherUpdateSchema,
    PCVOut as PeriodClosingVoucherOutSchema,
)

from app.application_accounting.chart_of_accounts.services.pcv_service import PeriodClosingVoucherService

from app.application_accounting.chart_of_accounts.schemas.cost_center_schemas import (
    CostCenterCreate,
    CostCenterUpdate,
)
from app.application_accounting.chart_of_accounts.services.cost_center_services import (
    CostCenterService,
)
from app.application_accounting.chart_of_accounts.services.journal_service import JournalEntryService

from app.application_accounting.chart_of_accounts.services.payment_service import PaymentEntryService
from app.business_validation.error_handling import format_validation_error
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user
from config.database import db

bp = Blueprint("accounting", __name__, url_prefix="/api/accounting")
logger = logging.getLogger(__name__)

fiscal_year_svc = FiscalYearService()
cost_center_svc = CostCenterService()
policies_svc = PoliciesService()

def _get_context() -> AffiliationContext:
    """Match buying endpoints style: attach ctx and fail cleanly if missing."""
    _ = get_current_user()  # Ensures user is authenticated and g.auth is set
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Authentication context not found.")
    return ctx

# ======================= Period Closing Voucher =======================


@bp.post("/period-closing-vouchers/create")
@require_permission("PeriodClosingVoucher", "CREATE")
def create_period_closing_voucher():
    try:
        ctx = _get_context()
        payload = PeriodClosingVoucherCreateSchema.model_validate(request.get_json(silent=True) or {})
        svc = PeriodClosingVoucherService(db.session)
        pcv = svc.create(payload=payload, ctx=ctx)
        return api_success(
            message="Period Closing Voucher created.",
            data={"id": pcv.id, "code": pcv.code, "doc_status": str(pcv.doc_status)},
            status_code=201,
        )
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
    except Exception as e:
        logger.exception("create_period_closing_voucher: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.put("/period-closing-vouchers/<int:pcv_id>/update")
@require_permission("PeriodClosingVoucher", "UPDATE")
def update_period_closing_voucher(pcv_id: int):
    try:
        ctx = _get_context()
        payload = PeriodClosingVoucherUpdateSchema.model_validate(request.get_json(silent=True) or {})
        svc = PeriodClosingVoucherService(db.session)
        pcv = svc.update(pcv_id=pcv_id, payload=payload, ctx=ctx)
        return api_success(
            message="Period Closing Voucher updated.",
            data={"id": pcv.id, "code": pcv.code, "doc_status": str(pcv.doc_status)},
            status_code=200,
        )
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound, Conflict) as e:
        return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
    except Exception as e:
        logger.exception("update_period_closing_voucher: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

# @bp.post("/period-closing-vouchers/<int:pcv_id>/submit")
# @require_permission("PeriodClosingVoucher", "SUBMIT")
# def submit_period_closing_voucher(pcv_id: int):
#     try:
#         ctx = _get_context()
#         _ = PeriodClosingVoucherSubmitSchema.model_validate(request.get_json(silent=True) or {})
#         svc = PeriodClosingVoucherService(db.session)
#         pcv = svc.submit(pcv_id=pcv_id, ctx=ctx)
#         return api_success(
#             message="Period Closing Voucher submitted.",
#             data={
#                 "id": pcv.id,
#                 "code": pcv.code,
#                 "doc_status": str(pcv.doc_status),
#                 "generated_journal_entry_id": pcv.generated_journal_entry_id,
#             },
#             status_code=200,
#         )
#     except ValidationError as e:
#         return api_error(format_validation_error(e), status_code=422)
#     except BizValidationError as e:
#         return api_error(str(e), status_code=422)
#     except (BadRequest, Forbidden, NotFound, Conflict) as e:
#         return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
#     except Exception as e:
#         logger.exception("submit_period_closing_voucher: %s", str(e))
#         return api_error("An unexpected error occurred.", status_code=500)
#
# @bp.post("/period-closing-vouchers/<int:pcv_id>/cancel")
# @require_permission("PeriodClosingVoucher", "CANCEL")
# def cancel_period_closing_voucher(pcv_id: int):
#     try:
#         ctx = _get_context()
#         payload = PeriodClosingVoucherCancelSchema.model_validate(request.get_json(silent=True) or {})
#         svc = PeriodClosingVoucherService(db.session)
#         pcv = svc.cancel(pcv_id=pcv_id, ctx=ctx, reason=payload.reason)
#         return api_success(
#             message="Period Closing Voucher cancelled.",
#             data={"id": pcv.id, "code": pcv.code, "doc_status": str(pcv.doc_status)},
#             status_code=200,
#         )
#     except ValidationError as e:
#         return api_error(format_validation_error(e), status_code=422)
#     except BizValidationError as e:
#         return api_error(str(e), status_code=422)
#     except (BadRequest, Forbidden, NotFound, Conflict) as e:
#         return api_error(e.description if hasattr(e, "description") else str(e), status_code=getattr(e, "code", 400))
#     except Exception as e:
#         logger.exception("cancel_period_closing_voucher: %s", str(e))
#         return api_error("An unexpected error occurred.", status_code=500)


# ------------------------- Fiscal Year -------------------------

@bp.post("/fiscal-years/create")
@require_permission("FiscalYear", "CREATE")
def create_fiscal_year():
    """Create a fiscal year. Accepts JSON regardless of Content-Type (silent=True)."""
    try:
        ctx = _get_context()
        payload = FiscalYearCreate.model_validate(request.get_json(silent=True) or {})
        fy = fiscal_year_svc.create_fiscal_year(payload, ctx)

        return api_success(
            message="Fiscal Year created.",
            data={"name": fy.name},
            status_code=201,
        )

    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        # Short, ERP-style messages from service/validators
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error in create_fiscal_year: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/fiscal-years/<int:fiscal_year_id>/update")
@require_permission("FiscalYear", "UPDATE")
def update_fiscal_year(fiscal_year_id: int):
    """
    Update fiscal year (supports name, start_date, end_date, status).
    Uses the same short message conventions as ERPNext.
    """
    try:
        ctx = _get_context()
        payload = FiscalYearUpdate.model_validate(request.get_json(silent=True) or {})
        fy = fiscal_year_svc.update_fiscal_year(fiscal_year_id, payload, ctx)

        return api_success(
            message="Fiscal Year updated.",
            data={"name": fy.name},
            status_code=200,
        )

    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error in update_fiscal_year: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)




# ------------------------- Cost Center -------------------------

@bp.post("/cost-centers/create")
@require_permission("CostCenter", "CREATE")
def create_cost_center():
    try:
        ctx = _get_context()
        payload = CostCenterCreate.model_validate(request.get_json(silent=True) or {})
        cc = cost_center_svc.create_cost_center(payload, ctx)

        return api_success(
            message="Cost Center created.",
            data={"name": cc.name},
            status_code=201,
        )

    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error in create_cost_center: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/cost-centers/<int:cost_center_id>/update")
@require_permission("CostCenter", "UPDATE")
def update_cost_center(cost_center_id: int):
    try:
        ctx = _get_context()
        payload = CostCenterUpdate.model_validate(request.get_json(silent=True) or {})
        cc = cost_center_svc.update_cost_center(cost_center_id, payload, ctx)

        return api_success(
            message="Cost Center updated.",
            data={"name": cc.name},
            status_code=200,
        )

    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=422)
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        logger.exception("Unexpected error in update_cost_center: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

# ------------------------- Mode of Payment -------------------------

@bp.post("/modes-of-payment/create")
@require_permission("ModeOfPayment", "CREATE")
def create_mode_of_payment():
    try:
        ctx = _get_context()
        payload = ModeOfPaymentCreate.model_validate(request.get_json(silent=True) or {})
        mop = policies_svc.create_mode_of_payment(payload, ctx)
        return api_success(
            message="Mode of Payment created.",
            data={"name": mop.name},
            status_code=201,
        )
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("create_mode_of_payment: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.put("/modes-of-payment/<int:mop_id>/update")
@require_permission("ModeOfPayment", "UPDATE")
def update_mode_of_payment(mop_id: int):
    try:
        ctx = _get_context()
        payload = ModeOfPaymentUpdate.model_validate(request.get_json(silent=True) or {})
        mop = policies_svc.update_mode_of_payment(mop_id, payload, ctx)
        return api_success(
            message="Mode of Payment updated.",
            data={"name": mop.name},
            status_code=200,
        )
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("update_mode_of_payment: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

# ------------------------- Account Access Policies -------------------------

@bp.post("/account-access-policies/create")
@require_permission("AccountAccessPolicy", "CREATE")
def create_account_access_policy():  # ← Changed function name
    try:
        ctx = _get_context()
        payload = AccountAccessPolicyCreate.model_validate(request.get_json(silent=True) or {})  # ← Use correct schema
        policy = policies_svc.create_access_policy(payload, ctx)  # ← Use correct service method
        return api_success(
            message="Access Policy created.",  # ← Updated message
            data={"id": policy.id},
            status_code=201,
        )
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("create_account_access_policy: %s", str(e))  # ← Updated log
        return api_error("An unexpected error occurred.", status_code=500)

@bp.put("/account-access-policies/<int:policy_id>/update")
@require_permission("AccountAccessPolicy", "UPDATE")
def update_account_access_policy(policy_id: int):  # ← Changed function name
    try:
        ctx = _get_context()
        payload = AccountAccessPolicyUpdate.model_validate(request.get_json(silent=True) or {})  # ← Use correct schema
        policy = policies_svc.update_access_policy(policy_id, payload, ctx)  # ← Use correct service method
        return api_success(
            message="Access Policy updated.",  # ← Updated message
            data={"id": policy.id},
            status_code=200,
        )
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("update_account_access_policy: %s", str(e))  # ← Updated log
        return api_error("An unexpected error occurred.", status_code=500)




# ------------------------- Payments (Payment Entry) -------------------------

_FIELD_LABELS = {
    "company_id": "Company",
    "branch_id": "Branch",
    "code": "Document Number",
    "payment_type": "Payment Type",
    "posting_date": "Posting Date",
    "mode_of_payment_id": "Payment Method",
    "party_type": "Party Type",
    "party_id": "Party",
    "paid_from_account_id": "Account Paid From",
    "paid_to_account_id": "Account Paid To",
    "paid_amount": "Paid Amount",
    "items": "Allocations",
}

def _label_for(field: str) -> str:
    return _FIELD_LABELS.get(field, field.replace("_", " ").title())

def _format_payment_validation_error(e: ValidationError) -> str:
    try:
        errs = e.errors()
    except Exception:
        return "Missing or invalid values."

    missing: list[str] = []
    others: list[str] = []

    for err in errs:
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        raw = str(err.get("msg") or "").strip()
        msg = raw.lower()
        label = _label_for(field) if field else "Field"

        if "field required" in msg or err.get("type") in {"missing", "value_error.missing"}:
            if label not in missing:
                missing.append(label)
            continue

        if "greater than" in msg or "should be greater than" in msg:
            # e.g. "Input should be greater than 0"
            bound = err.get("ctx", {}).get("gt")
            bound_text = str(bound) if bound is not None else "0"
            others.append(f"{label} must be greater than {bound_text}")
            continue

        if "valid date" in msg or "date" in msg:
            others.append(f"{label} is invalid")
            continue

        if field:
            others.append(f"Invalid value for {label}")
        else:
            others.append("Missing or invalid values.")

    if missing and not others:
        return "Missing fields: " + ", ".join(missing)
    if missing and others:
        return "Missing fields: " + ", ".join(missing) + ". " + "; ".join(others)
    if others:
        return "; ".join(others)
    return "Missing or invalid values."
@bp.post("/payments/create")
@require_permission("PaymentEntry", "CREATE")
def create_payment_entry():
    try:
        ctx = _get_context()
        payload = PaymentCreateSchema.model_validate(request.get_json(silent=True) or {})
        svc = PaymentEntryService()
        pe = svc.create(payload=payload.model_dump(), context=ctx)
        return api_success(
            message="Payment Entry created.",
            data={"id": pe.id, "code": pe.code},
            status_code=201
        )
    except ValidationError as e:
        friendly = _format_payment_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Invalid reference: check accounts and party.", status_code=422)
    except Exception as e:
        logger.exception("create_payment_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.put("/payments/<int:payment_id>/update")
@require_permission("PaymentEntry", "UPDATE")
def update_payment_entry(payment_id: int):
    try:
        ctx = _get_context()
        payload = PaymentUpdateSchema.model_validate(request.get_json(silent=True) or {})
        svc = PaymentEntryService()
        pe = svc.update(payment_id=payment_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
        return api_success(
            message="Payment Entry updated.",
            data={"id": pe.id, "code": pe.code}
        )
    except ValidationError as e:
        friendly = _format_payment_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Invalid reference: check accounts and party.", status_code=422)
    except Exception as e:
        logger.exception("update_payment_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)



@bp.post("/payments/<int:payment_id>/submit")
@require_permission("PaymentEntry", "SUBMIT")
def submit_payment_entry(payment_id: int):
    try:
        ctx = _get_context()
        payload = PaymentSubmitSchema.model_validate(request.get_json(silent=True) or {})
        svc = PaymentEntryService()
        pe = svc.submit(payment_id=payment_id, context=ctx, auto_allocate=bool(payload.auto_allocate))
        return api_success(
            message="Payment Entry submitted.",
            data={"id": pe.id, "code": pe.code, "doc_status": str(pe.doc_status)}
        )
    except ValidationError as e:
        friendly = _format_payment_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("submit_payment_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/payments/<int:payment_id>/cancel")
@require_permission("PaymentEntry", "CANCEL")
def cancel_payment_entry(payment_id: int):
    try:
        ctx = _get_context()
        payload = PaymentCancelSchema.model_validate(request.get_json(silent=True) or {})
        svc = PaymentEntryService()
        pe = svc.cancel(payment_id=payment_id, context=ctx, reason=payload.reason)
        return api_success(
            message="Payment Entry cancelled.",
            data={"id": pe.id, "code": pe.code, "doc_status": str(pe.doc_status)}
        )
    except ValidationError as e:
        friendly = _format_payment_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("cancel_payment_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.get("/payments/outstanding")
@require_permission("PaymentEntry", "READ")
def list_outstanding_invoices():
    try:
        ctx = _get_context()  # Get the authentication context

        # parse query params via Pydantic for consistency
        payload = OutstandingFilter.model_validate({
            "party_kind": request.args.get("party_kind"),
            "party_id": request.args.get("party_id"),
            "posting_from": request.args.get("posting_from"),
            "posting_to": request.args.get("posting_to"),
            "due_from": request.args.get("due_from"),
            "due_to": request.args.get("due_to"),
            "gt_amount": request.args.get("gt_amount"),
            "lt_amount": request.args.get("lt_amount"),
            "limit": request.args.get("limit", 200),
        })

        svc = PaymentEntryService()

        # Use company_id from the context - this is the correct attribute
        company_id = ctx.company_id

        if not company_id:
            return api_error("Company context is required to fetch outstanding invoices", status_code=422)

        rows = svc.get_outstanding(
            company_id=company_id,  # Use the correct company_id from context
            party_kind=payload.party_kind,
            party_id=payload.party_id,
            posting_from=payload.posting_from,
            posting_to=payload.posting_to,
            due_from=payload.due_from,
            due_to=payload.due_to,
            gt_amount=payload.gt_amount,
            lt_amount=payload.lt_amount,
            limit=payload.limit or 200,
        )

        if not rows:
            who = (payload.party_kind or "party").lower()
            return api_success(data={"rows": [],
                                     "message": f"No outstanding invoices found for the {who} which qualify the filters you have specified."})

        return api_success(data={"rows": rows})

    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except PermissionError as e:
        return api_error("Authentication required", status_code=401)
    except Exception as e:
        logger.exception("list_outstanding_invoices: %s", str(e))
        return api_error("Invalid query", status_code=422)



# ------------------------- Expenses -------------------------


_FIELD_LABELS.update({
    "expense_type": "Expense Type",
    "account_id": "Expense Account",
    "paid_from_account_id": "Paid From Account",
    "amount": "Amount",
    "items": "Expense Items",
    "name": "Name",
    "default_account_id": "Default Account",
})


def _format_expense_validation_error(e: ValidationError) -> str:
    """Format expense-specific validation errors with ERP-style messages."""
    try:
        errs = e.errors()
    except Exception:
        return "Missing or invalid values."

    missing: list[str] = []
    others: list[str] = []

    for err in errs:
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        raw = str(err.get("msg") or "").strip()
        msg = raw.lower()
        label = _label_for(field) if field else "Field"

        # Handle specific expense validation messages
        if "add at least one expense item" in msg:
            missing.append("Expense Items")
            continue

        if "expense account and payment account must be different" in msg:
            others.append("Expense account and payment account must be different")
            continue

        if "field required" in msg or err.get("type") in {"missing", "value_error.missing"}:
            if label not in missing:
                missing.append(label)
            continue

        if "greater than" in msg or "should be greater than" in msg:
            bound = err.get("ctx", {}).get("gt")
            bound_text = str(bound) if bound is not None else "0"
            others.append(f"{label} must be greater than {bound_text}")
            continue

        if field:
            others.append(f"Invalid value for {label}")
        else:
            others.append("Missing or invalid values.")

    if missing and not others:
        return "Mandatory fields required in Expenses: " + ", ".join(missing)
    if missing and others:
        return "Mandatory fields required in Expenses: " + ", ".join(missing) + ". " + "; ".join(others)
    if others:
        return "; ".join(others)
    return "Missing or invalid values."


def _format_expense_type_validation_error(e: ValidationError) -> str:
    """Format expense type validation errors."""
    try:
        errs = e.errors()
    except Exception:
        return "Missing or invalid values."

    missing: list[str] = []
    others: list[str] = []

    for err in errs:
        loc = err.get("loc") or ()
        field = str(loc[-1]) if loc else ""
        raw = str(err.get("msg") or "").strip()
        msg = raw.lower()  # FIXED: Define msg variable here
        label = _label_for(field) if field else "Field"

        if "field required" in msg or err.get("type") in {"missing", "value_error.missing"}:
            if label not in missing:
                missing.append(label)
            continue

        if "greater than" in msg or "should be greater than" in msg:
            bound = err.get("ctx", {}).get("gt")
            bound_text = str(bound) if bound is not None else "0"
            others.append(f"{label} must be greater than {bound_text}")
            continue

        if field:
            others.append(f"Invalid value for {label}")
        else:
            others.append("Missing or invalid values.")

    if missing and not others:
        return "Mandatory fields required in Expense Type: " + ", ".join(missing)
    if missing and others:
        return "Mandatory fields required in Expense Type: " + ", ".join(missing) + ". " + "; ".join(others)
    if others:
        return "; ".join(others)
    return "Missing or invalid values."


# ------------------------- Expense Type Endpoints -------------------------

@bp.post("/expense-types/create")
@require_permission("ExpenseType", "CREATE")
def create_expense_type():
    try:
        ctx = _get_context()
        payload = ExpenseTypeCreate.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp_type = svc.create_expense_type(payload=payload.model_dump(), context=ctx)
        return api_success(
            message="Expense Type created successfully.",
            data={"id": exp_type.id, "name": exp_type.name},
            status_code=201
        )
    except ValidationError as e:
        friendly = _format_expense_type_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Expense Type with this name already exists.", status_code=422)
    except Exception as e:
        logger.exception("create_expense_type: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/expense-types/<int:expense_type_id>/update")
@require_permission("ExpenseType", "UPDATE")
def update_expense_type(expense_type_id: int):
    try:
        ctx = _get_context()
        payload = ExpenseTypeUpdate.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp_type = svc.update_expense_type(
            expense_type_id=expense_type_id,
            payload=payload.model_dump(exclude_unset=True),
            context=ctx
        )
        return api_success(
            message="Expense Type updated successfully.",
            data={"id": exp_type.id, "name": exp_type.name}
        )
    except ValidationError as e:
        friendly = _format_expense_type_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Expense Type with this name already exists.", status_code=422)
    except Exception as e:
        logger.exception("update_expense_type: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


# ------------------------- Expense Document Endpoints -------------------------

@bp.post("/expenses/create")
@require_permission("Expense", "CREATE")
def create_expense():
    try:
        ctx = _get_context()
        payload = ExpenseCreateSchema.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp = svc.create(payload=payload.model_dump(), context=ctx)
        return api_success(
            message="Expense created successfully.",
            data={"id": exp.id, "code": exp.code, "doc_status": str(exp.doc_status)},
            status_code=201
        )
    except ValidationError as e:
        friendly = _format_expense_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Invalid reference: check accounts and expense types.", status_code=422)
    except Exception as e:
        logger.exception("create_expense: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.put("/expenses/<int:expense_id>/update")
@require_permission("Expense", "UPDATE")
def update_expense(expense_id: int):
    try:
        ctx = _get_context()
        payload = ExpenseUpdateSchema.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp = svc.update(expense_id=expense_id, payload=payload.model_dump(exclude_unset=True), context=ctx)
        return api_success(
            message="Expense updated successfully.",
            data={"id": exp.id, "code": exp.code, "doc_status": str(exp.doc_status)}
        )
    except ValidationError as e:
        friendly = _format_expense_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except IntegrityError:
        return api_error("Invalid reference: check accounts and expense types.", status_code=422)
    except Exception as e:
        logger.exception("update_expense: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/expenses/<int:expense_id>/submit")
@require_permission("Expense", "SUBMIT")
def submit_expense(expense_id: int):
    try:
        ctx = _get_context()
        payload = ExpenseSubmitSchema.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp = svc.submit(expense_id=expense_id, context=ctx)
        return api_success(
            message="Expense submitted successfully.",
            data={"id": exp.id, "code": exp.code, "doc_status": str(exp.doc_status)}
        )
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("submit_expense: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.post("/expenses/<int:expense_id>/cancel")
@require_permission("Expense", "CANCEL")
def cancel_expense(expense_id: int):
    try:
        ctx = _get_context()
        payload = ExpenseCancelSchema.model_validate(request.get_json(silent=True) or {})
        svc = ExpenseService()
        exp = svc.cancel(expense_id=expense_id, context=ctx, reason=payload.reason)
        return api_success(
            message="Expense cancelled successfully.",
            data={"id": exp.id, "code": exp.code, "doc_status": str(exp.doc_status)}
        )
    except ValidationError as e:
        friendly = _format_expense_validation_error(e)
        return api_error(friendly, status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("cancel_expense: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


# ========================= Manual Journal Entry =========================


@bp.post("/journal-entries/create")
@require_permission("JournalEntry", "CREATE")
def create_journal_entry():
    try:
        ctx = _get_context()
        payload = JournalEntryCreateSchema.model_validate(request.get_json(silent=True) or {})
        svc = JournalEntryService(db.session)
        je = svc.create(payload=payload, ctx=ctx)
        return api_success(message="Journal Entry created.",
                           data={"id": je.id, "code": je.code, "doc_status": str(je.doc_status)},
                           status_code=201)
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except (BizValidationError, Conflict) as e:
        return api_error(str(e), status_code=422)
    except (BadRequest, Forbidden, NotFound) as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        logger.exception("create_journal_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.put("/journal-entries/<int:je_id>/update")
@require_permission("JournalEntry", "UPDATE")
def update_journal_entry(je_id: int):
    try:
        ctx = _get_context()
        payload = JournalEntryUpdateSchema.model_validate(request.get_json(silent=True) or {})
        svc = JournalEntryService(db.session)
        je = svc.update(je_id=je_id, payload=payload, ctx=ctx)
        return api_success(message="Journal Entry updated.",
                           data={"id": je.id, "code": je.code, "doc_status": str(je.doc_status)})
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("update_journal_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.post("/journal-entries/<int:je_id>/submit")
@require_permission("JournalEntry", "SUBMIT")
def submit_journal_entry(je_id: int):
    try:
        ctx = _get_context()
        _ = JournalEntrySubmitSchema.model_validate(request.get_json(silent=True) or {})
        svc = JournalEntryService(db.session)
        je = svc.submit(je_id=je_id, ctx=ctx)
        return api_success(message="Journal Entry submitted.",
                           data={"id": je.id, "code": je.code, "doc_status": str(je.doc_status)})
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("submit_journal_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

@bp.post("/journal-entries/<int:je_id>/cancel")
@require_permission("JournalEntry", "CANCEL")
def cancel_journal_entry(je_id: int):
    try:
        ctx = _get_context()
        payload = JournalEntryCancelSchema.model_validate(request.get_json(silent=True) or {})
        svc = JournalEntryService(db.session)
        je = svc.cancel(je_id=je_id, ctx=ctx, reason=payload.reason)
        return api_success(message="Journal Entry cancelled.",
                           data={"id": je.id, "code": je.code, "doc_status": str(je.doc_status)})
    except ValidationError as e: 
        return api_error(format_validation_error(e), status_code=422)
    except BizValidationError as e:
        return api_error(str(e), status_code=422)
    except Exception as e:
        logger.exception("cancel_journal_entry: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)

