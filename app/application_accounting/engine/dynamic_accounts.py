# application_accounting/engine/dynamic_accounts.py
from __future__ import annotations
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from app.application_accounting.engine.errors import AccountNotFoundError
from app.application_accounting.engine.selectors import get_account_id_by_code


def resolve_account_id(
    s: Session,
    *, company_id: int,
    static_account_code: Optional[str],
    requires_dynamic_account: bool,
    context_key: Optional[str],
    runtime_context: Dict[str, Any],
) -> int:
    """
    If static_account_code is present, map to account_id; else pull from runtime_context[context_key].
    """
    if not requires_dynamic_account and static_account_code:
        aid = get_account_id_by_code(s, company_id, static_account_code)
        if not aid:
            raise AccountNotFoundError(f"Static account code {static_account_code} not found in company {company_id}.")
        return aid

    if requires_dynamic_account:
        if not context_key:
            raise AccountNotFoundError("Dynamic account required but context_key is missing.")
        aid = runtime_context.get(context_key)
        if not aid:
            raise AccountNotFoundError(f"Dynamic account '{context_key}' not provided in runtime context.")
        return int(aid)

    raise AccountNotFoundError("Unable to resolve account id (invalid template line).")
