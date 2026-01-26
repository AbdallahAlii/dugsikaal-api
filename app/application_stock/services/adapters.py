# app/application_stock/services/adapters.py
from __future__ import annotations

from typing import Any, Dict

from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.application_stock.services.reconciliation_service import (
    StockReconciliationService,
)


def _ctx_from_row(row: Dict[str, Any]) -> AffiliationContext:
    """
    Build AffiliationContext for stock import.

    - company_id / branch_id / created_by_id are injected from DataImport
      via _inject_context() in the pipeline.
    - We mark is_system_admin=True because authorization was already
      enforced at Data Import endpoint.
    """
    company_id = int(row.get("company_id") or 0)
    branch_id_raw = row.get("branch_id")
    branch_id = int(branch_id_raw) if branch_id_raw is not None else None

    user_id_raw = row.get("created_by_id")
    user_id = int(user_id_raw) if user_id_raw is not None else 0

    return AffiliationContext(
        user_id=user_id,
        user_type=row.get("user_type") or "user",
        company_id=company_id,
        branch_id=branch_id,
        roles=set(),
        affiliations=[],
        permissions=set(),
        is_system_admin=True,
    )


def create_stock_reconciliation_via_import(row: Dict[str, Any]) -> None:
    """
    Single-row handler: one Stock Reconciliation document per row.

    The row dict is already:
    - resolved: item_id / warehouse_id / difference_account_id (IDs)
      via resolve_links_bulk + registry resolvers.
    - enriched with company_id / branch_id / created_by_id.
    - contains internal flags: _submit_after_import, _mute_emails.
    """
    ctx = _ctx_from_row(row)

    # IMPORTANT:
    # auto_commit=False because the Data Import pipeline controls
    # transactions (Session.begin / begin_nested). We must not commit()
    # or rollback() here, otherwise we hit "closed transaction inside
    # context manager" errors.
    svc = StockReconciliationService(session=db.session, auto_commit=False)

    # Meta flags (remove from row so they don't go into payload)
    submit_after = bool(row.pop("_submit_after_import", False))
    row.pop("_mute_emails", None)  # not used here, but safe to drop

    # Build payload in the same shape that your HTTP API expects:
    payload: Dict[str, Any] = {
        "company_id": row.get("company_id"),
        "branch_id": row.get("branch_id"),
        "posting_date": row.get("posting_date"),
        "purpose": row.get("purpose") or "Stock Reconciliation",
        "notes": row.get("notes"),
        "difference_account_id": row.get("difference_account_id"),
        "items": [
            {
                "item_id": row.get("item_id"),
                "warehouse_id": row.get("warehouse_id"),
                "quantity": row.get("quantity"),
                "valuation_rate": row.get("valuation_rate"),
            }
        ],
    }

    # 1) Create as Draft (no commit; only flush under the hood)
    recon = svc.create_stock_reconciliation(
        payload=payload,
        context=ctx,
    )

    # 2) Optionally submit (Opening Stock or normal Stock Reconciliation)
    if submit_after:
        svc.submit_stock_reconciliation(
            recon_id=recon.id,
            context=ctx,
        )
