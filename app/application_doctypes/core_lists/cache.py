
# app/application_doctypes/core_lists/cache.py
from __future__ import annotations
import hashlib, logging
from typing import Iterable, Mapping, Any, Optional

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import _is_system_admin
from .config import ListConfig, CacheScope

log = logging.getLogger(__name__)

def _sorted_unique(iterable: Iterable) -> list:
    return sorted(set(iterable))

def _get_from_filters(params: Mapping[str, Any], key: str) -> Optional[int]:
    # params looks like: {"page":..., "per_page":..., "filters": {...}, ...}
    filters = (params or {}).get("filters") or {}
    val = filters.get(key)
    try:
        return int(val) if val is not None else None
    except Exception:
        return None

def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

def build_list_scope_key(cfg: ListConfig, context: AffiliationContext, *, params: Mapping[str, Any]) -> str:
    """
    Compute the cache scope key for a list read.
      GLOBAL  -> "global" (admins: "sys-admin")
      COMPANY -> "co:<company_id>"  (fallback: hash of visible companies)
      BRANCH  -> "br:<company_id>-<branch_id>" (fallback: "co:<company_id>", then hash of pairs)
    """
    is_admin = _is_system_admin(context)
    scope: CacheScope = cfg.cache_scope  # normalized by ListConfig.__init__

    # 1) Prefer request filters
    company_id = _get_from_filters(params, "company_id")
    branch_id  = _get_from_filters(params, "branch_id")

    # 2) Fall back to primary affiliation on context
    company_id = company_id or getattr(context, "company_id", None)
    branch_id  = branch_id  or getattr(context, "branch_id", None)

    # 3) Full affiliation set (for fallbacks)
    affs = list(getattr(context, "affiliations", []) or [])

    if scope == CacheScope.GLOBAL:
        key = "sys-admin" if is_admin else "global"
        log.debug("[lists] scope=GLOBAL -> %s", key)
        return key

    if scope == CacheScope.COMPANY:
        if company_id:
            key = f"co:{company_id}"
            log.debug("[lists] scope=COMPANY -> %s", key)
            return key
        # fallback: stable hash of visible companies
        cos = _sorted_unique([a.company_id for a in affs if getattr(a, "company_id", None)])
        key = _hash("co:" + ",".join(map(str, cos)))
        log.debug("[lists] scope=COMPANY (fallback) -> %s (companies=%s)", key, cos)
        return key

    # BRANCH scope
    if company_id and branch_id:
        key = f"br:{company_id}-{branch_id}"
        log.debug("[lists] scope=BRANCH -> %s", key)
        return key
    if company_id:
        key = f"co:{company_id}"
        log.debug("[lists] scope=BRANCH (fallback to company) -> %s", key)
        return key

    pairs = _sorted_unique(
        [(a.company_id, a.branch_id)
         for a in affs if getattr(a, "company_id", None) and getattr(a, "branch_id", None)]
    )
    key = _hash("br:" + ",".join([f"{c}-{b}" for c, b in pairs]))
    log.debug("[lists] scope=BRANCH (fallback hash) -> %s (pairs=%s)", key, pairs)
    return key
