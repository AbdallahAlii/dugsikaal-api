# app/party/endpoints.py
from flask import Blueprint, request, g
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from app.application_parties.schemas import PartyCreate, PartyUpdate, PartyBulkDelete
from app.application_parties.services import PartyService, PartyLogicError
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext
from app.auth.deps import get_current_user

bp = Blueprint("party", __name__, url_prefix="/api/parties")
svc = PartyService()




@bp.post("/create")
@require_permission("Party", "CREATE")
def create_party():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload_data = request.get_json(silent=True) or {}
        branch_id = payload_data.pop("branch_id", None)
        payload = PartyCreate.model_validate(payload_data)

        new_party = svc.create_party(payload=payload, context=ctx, branch_id=branch_id)

        response_data = {
            "party_id": new_party.id,
            "code": new_party.code
        }

        return api_success(
            message="Party created successfully.",
            data=response_data,
            status_code=201
        )

    except (PartyLogicError, ValidationError) as e:
        # FIX: Check if the exception is a PartyLogicError
        if isinstance(e, PartyLogicError):
            # Only return the custom message from your business logic
            return api_error(e.description, status_code=422)
        else:
            # For other exceptions (like ValidationError), return the full string
            return api_error(str(e), status_code=422)

    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)

@bp.put("/update/<int:party_id>")
@require_permission("Party", "UPDATE")
def update_party(party_id: int):
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = PartyUpdate.model_validate(request.get_json(silent=True) or {})

        updated_party = svc.update_party(party_id=party_id, payload=payload, context=ctx)

        return api_success(
            message="Party updated successfully.",
            data={},
            status_code=200
        )

    except (PartyLogicError, ValidationError) as e:
        # FIX: Check for PartyLogicError and return only the message
        if isinstance(e, PartyLogicError):
            return api_error(e.description, status_code=422)
        else:
            return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)


@bp.delete("/delete")
@require_permission("Party", "DELETE")
def bulk_delete_parties():
    _ = get_current_user()
    try:
        ctx: AffiliationContext = getattr(g, "auth")
        payload = PartyBulkDelete.model_validate(request.get_json(silent=True) or {})
        if not payload.ids:
            return api_error("No party IDs provided.", status_code=422)

        result = svc.bulk_delete_parties(payload=payload, context=ctx)

        return api_success(message="Parties deleted successfully.", data={}, status_code=200)

    except (PartyLogicError, ValidationError) as e:
        # FIX: Check for PartyLogicError and return only the message
        if isinstance(e, PartyLogicError):
            return api_error(e.description, status_code=422)
        else:
            return api_error(str(e), status_code=422)
    except HTTPException as e:
        return api_error(e.description, status_code=e.code)
    except Exception as e:
        return api_error(f"An unexpected server error occurred: {e}", status_code=500)