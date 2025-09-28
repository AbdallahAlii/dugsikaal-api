# app/application_doctypes/core_dropdowns/cache.py
from __future__ import annotations
import hashlib, logging
from typing import Iterable, Mapping, Any, Optional
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin
from app.application_doctypes.core_lists.config import CacheScope
from .config import DropdownConfig

log = logging.getLogger(__name__)

def _sorted_unique(iterable: Iterable) -> list:
    return sorted(set(iterable))

def _get_from_params(params: Mapping[str, Any], key: str) -> Optional[int]:
    raw = (params or {}).get(key)
    try:
        return int(raw) if raw is not None else None
    except Exception:
        return None

def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def build_dropdown_scope_key(cfg: DropdownConfig, context: AffiliationContext, *, params: Mapping[str, Any]) -> str:
    """
    GLOBAL  -> "global" (admins share "sys-admin")
    COMPANY -> "co:<company_id>" or hash of visible companies
    BRANCH  -> "br:<company_id>-<branch_id>" or fallback to "co:<company_id>" then hash of pairs
    """
    is_admin = _is_system_admin(context)
    scope: CacheScope = cfg.cache_scope

    company_id = _get_from_params(params, "company_id") or getattr(context, "company_id", None)
    branch_id  = _get_from_params(params, "branch_id")  or getattr(context, "branch_id", None)
    affs = list(getattr(context, "affiliations", []) or [])

    if scope == CacheScope.GLOBAL:
        return "sys-admin" if is_admin else "global"

    if scope == CacheScope.COMPANY:
        if company_id:
            return f"co:{company_id}"
        cos = _sorted_unique([a.company_id for a in affs if getattr(a, "company_id", None)])
        return _hash("co:" + ",".join(map(str, cos)))

    # BRANCH
    if company_id and branch_id:
        return f"br:{company_id}-{branch_id}"
    if company_id:
        return f"co:{company_id}"
    pairs = _sorted_unique(
        [(a.company_id, a.branch_id) for a in affs
         if getattr(a, "company_id", None) and getattr(a, "branch_id", None)]
    )
    return _hash("br:" + ",".join([f"{c}-{b}" for c, b in pairs]))
