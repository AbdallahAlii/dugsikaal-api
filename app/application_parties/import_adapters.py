# app/application_parties/import_adapters.py

from __future__ import annotations
from typing import Any, Dict

from werkzeug.exceptions import BadRequest

from config.database import db
from app.security.rbac_effective import AffiliationContext

from app.application_parties.parties_models import PartyRoleEnum
from app.application_parties.services import PartyService
from app.application_parties.schemas import PartyCreate  # used by PartyService


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build an AffiliationContext for the importer.

    - company_id / branch_id / created_by_id are injected in the pipeline
      (see _inject_context in application_data_import/runner/pipeline.py).
    - We mark is_system_admin=True so that scope checks don't reject
      imports that are already authorized at the Data Import endpoint.
    """
    company_id = int(row.get("company_id") or 0)
    branch_id_raw = row.get("branch_id")
    branch_id = int(branch_id_raw) if branch_id_raw is not None else None

    user_id_raw = row.get("created_by_id")
    user_id = int(user_id_raw) if user_id_raw is not None else 0

    # roles / permissions are not critical for imports; keep them empty/set
    raw_roles = row.get("roles")
    if isinstance(raw_roles, (list, set, tuple)):
        roles = set(raw_roles)
    elif isinstance(raw_roles, str) and raw_roles.strip():
        roles = {r.strip() for r in raw_roles.split(",") if r.strip()}
    else:
        roles = set()

    raw_permissions = row.get("permissions")
    if isinstance(raw_permissions, (list, set, tuple)):
        permissions = set(raw_permissions)
    elif isinstance(raw_permissions, str) and raw_permissions.strip():
        permissions = {p.strip() for p in raw_permissions.split(",") if p.strip()}
    else:
        permissions = set()

    affiliations: list = []

    return AffiliationContext(
        user_id=user_id,
        user_type=row.get("user_type") or "user",
        company_id=company_id,
        branch_id=branch_id,
        roles=roles,
        affiliations=affiliations,
        permissions=permissions,
        is_system_admin=True,
    )


def _build_party_payload(row: Dict[str, Any], role: PartyRoleEnum) -> PartyCreate:
    """
    Map a resolved row dict into PartyCreate payload.

    Excel headers are already mapped to fieldnames by the import pipeline,
    using the registry template.labels. So we expect keys like:

    - name
    - phone
    - nature         (from 'Customer Type' or 'Supplier Type' header)
    - email
    - address_line1
    - city_id
    - notes
    - is_cash_party  (optional)

    role is always forced by the adapter (Customer / Supplier).
    """
    allowed_fields = {
        "code",          # optional: if not provided, PartyService will generate
        "name",
        "nature",
        "email",
        "phone",
        "address_line1",
        "city_id",
        "notes",
        "is_cash_party",
    }

    data: Dict[str, Any] = {
        k: v for k, v in row.items()
        if k in allowed_fields and v is not None
    }

    # Force role (Excel must NOT control this)
    data["role"] = role

    # If is_cash_party not provided, let it default to False
    if "is_cash_party" not in data or data["is_cash_party"] is None:
        data["is_cash_party"] = False

    # Basic validation for name / phone / nature presence;
    # header-level validator already checks required columns, but
    # this guards against completely empty values.
    missing_core = []
    for field in ("name", "phone", "nature"):
        if not str(data.get(field, "")).strip():
            missing_core.append(field)
    if missing_core:
        raise BadRequest(
            "Missing required values: " + ", ".join(missing_core)
        )

    return PartyCreate(**data)


def create_customer_via_import(row: Dict[str, Any]) -> None:
    """
    Adapter for registry.handlers.create on DocType 'Customer'.
    """
    ctx = _ctx_from_row(row)

    # IMPORTANT:
    # autocommit=False so that the Data Import pipeline's
    # `with db.session.begin_nested(): ...` fully controls
    # commit/rollback per row (ERP-style).
    svc = PartyService(session=db.session, autocommit=False)

    payload = _build_party_payload(row, PartyRoleEnum.CUSTOMER)

    # Ensure branch_id and company_id are passed correctly from the row data
    branch_id = row.get("branch_id")
    company_id = row.get("company_id")

    # build_dto=False -> do NOT call Pydantic DTO builder here.
    # We only need to persist; the pipeline will log success or failure.
    svc.create_party(
        payload,
        ctx,
        branch_id=branch_id,
        company_id=company_id,
        build_dto=False,
    )


def create_supplier_via_import(row: Dict[str, Any]) -> None:
    """
    Adapter for registry.handlers.create on DocType 'Supplier'.
    """
    ctx = _ctx_from_row(row)
    svc = PartyService(session=db.session, autocommit=False)

    payload = _build_party_payload(row, PartyRoleEnum.SUPPLIER)

    branch_id = row.get("branch_id")
    company_id = row.get("company_id")

    svc.create_party(
        payload,
        ctx,
        branch_id=branch_id,
        company_id=company_id,
        build_dto=False,
    )
