from __future__ import annotations
from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import NotFound, Conflict, Forbidden, BadRequest, HTTPException
import logging

from app.application_accounting.chart_of_accounts.schemas.account_policies_schemas import ModeOfPaymentCreate, \
    ModeOfPaymentUpdate, AccountAccessPolicyUpdate, AccountAccessPolicyCreate
from app.application_accounting.chart_of_accounts.schemas.fiscal_year_schemas import (
    FiscalYearCreate,
    FiscalYearUpdate,
)
from app.application_accounting.chart_of_accounts.services.account_policy_services import PoliciesService
from app.application_accounting.chart_of_accounts.services.fiscal_year_services import (
    FiscalYearService,
)
from app.application_accounting.chart_of_accounts.schemas.cost_center_schemas import (
    CostCenterCreate,
    CostCenterUpdate,
)
from app.application_accounting.chart_of_accounts.services.cost_center_services import (
    CostCenterService,
)
from app.business_validation.error_handling import format_validation_error
from app.business_validation.item_validation import BizValidationError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

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