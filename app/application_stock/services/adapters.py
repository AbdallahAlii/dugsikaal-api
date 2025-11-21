# app/application_stock/services/adapters.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from werkzeug.exceptions import BadRequest

from app.application_stock.services.reconciliation_service import StockReconciliationService
from app.security.rbac_effective import AffiliationContext
from config.database import db


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build an AffiliationContext for Data Import rows.

    IMPORTANT:
    - company_id / branch_id are injected by the pipeline from the DataImport row
      (see application_data_import.runner.pipeline._inject_context).
    - We **do not** hard-code any roles.
    - We keep is_system_admin=True so ensure_scope_by_ids() will not block the
      import job after the HTTP layer has already enforced "Data Import" permissions.
    """
    company_id = int(row.get("company_id") or 0)

    branch_id_raw = row.get("branch_id")
    branch_id = int(branch_id_raw) if branch_id_raw is not None else None

    user_id_raw = row.get("created_by_id")
    user_id = int(user_id_raw) if user_id_raw is not None else 0

    # ----- roles -----
    raw_roles = row.get("roles")
    if isinstance(raw_roles, (list, set, tuple)):
        roles = set(raw_roles)
    elif isinstance(raw_roles, str) and raw_roles.strip():
        roles = {r.strip() for r in raw_roles.split(",") if r.strip()}
    else:
        # No default business role; imports don't depend on roles
        roles = set()

    # ----- affiliations -----
    affiliations: list = []

    # ----- permissions -----
    raw_permissions = row.get("permissions")
    if isinstance(raw_permissions, (list, set, tuple)):
        permissions = set(raw_permissions)
    elif isinstance(raw_permissions, str) and raw_permissions.strip():
        permissions = {p.strip() for p in raw_permissions.split(",") if p.strip()}
    else:
        permissions = set()

    user_type = row.get("user_type") or "user"

    return AffiliationContext(
        user_id=user_id,
        user_type=user_type,
        company_id=company_id,
        branch_id=branch_id,
        roles=roles,
        affiliations=affiliations,
        permissions=permissions,
        is_system_admin=True,  # still system-level inside the import job
    )


def _require_field(row: Dict[str, Any], key: str) -> Any:
    if row.get(key) in (None, ""):
        raise BadRequest(f"Missing required field '{key}'.")
    return row[key]


def create_stock_reconciliation_via_import(row: Dict[str, Any]) -> None:
    """
    Data Import adapter for StockReconciliation.

    One CSV/Excel row -> one Stock Reconciliation document with ONE item line.

    Expected final (resolved) columns in `row` after the import pipeline:
      - company_id       (injected by pipeline)
      - branch_id        (injected by pipeline OR resolved by Branch Name)
      - created_by_id    (injected by pipeline)
      - posting_date     (date or ISO date string)
      - purpose          (optional, "Opening Stock" or "Stock Reconciliation")
      - difference_account_id (optional, resolved from Account Name)
      - notes            (optional)
      - code             (optional manual code)
      - item_id          (resolved from Item Name)
      - warehouse_id     (resolved from Warehouse Name)
      - quantity         (decimal / float / str)
      - valuation_rate   (optional decimal)
    """
    ctx = _ctx_from_row(row)
    svc = StockReconciliationService(session=db.session)

    # ---- Required core fields ----
    posting_date = _require_field(row, "posting_date")
    item_id = int(_require_field(row, "item_id"))
    warehouse_id = int(_require_field(row, "warehouse_id"))
    quantity = row.get("quantity")
    if quantity in (None, ""):
        raise BadRequest("Missing required field 'quantity'.")

    # Optional / header-level fields
    purpose = row.get("purpose")  # may be None -> service defaults to STOCK_RECONCILIATION
    notes = row.get("notes")
    difference_account_id = row.get("difference_account_id")
    code = row.get("code")
    valuation_rate = row.get("valuation_rate")

    payload: Dict[str, Any] = {
        # Header context – service will finalize company/branch via resolve_company_branch_and_scope
        "company_id": row.get("company_id"),
        "branch_id": row.get("branch_id"),

        "posting_date": posting_date,
        "purpose": purpose,
        "notes": notes,
        "difference_account_id": difference_account_id,
        "code": code,
        # Single line per document
        "items": [
            {
                "item_id": item_id,
                "warehouse_id": warehouse_id,
                "quantity": quantity,
                "valuation_rate": valuation_rate,
            }
        ],
    }

    # Service will:
    # - validate items/warehouses
    # - auto-pick difference account if not provided:
    #     OPENING_STOCK        -> "Temporary Opening"
    #     STOCK_RECONCILIATION -> "Stock Adjustments"
    # - create as DRAFT
    svc.create_stock_reconciliation(payload=payload, context=ctx)
