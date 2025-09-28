# # # # app/common/cache/cache_invalidator.py

from __future__ import annotations

import logging
from typing import Any, Optional

from .cache import get_version
from .core_cache import bump_version
from .cache_keys import detail_version_key, list_version_key, user_profile_version_key, build_detail_cache_key
from app.application_doctypes.core_lists.config import CacheScope, get_list_config
from app.application_doctypes.core_lists.cache import build_list_scope_key
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)

def bump_detail(entity: str, record_id: Any) -> int:
    v = bump_version(detail_version_key(entity, record_id))
    log.info("[cache] bump detail %s(%s) -> v%s", entity, record_id, v)
    return v

def invalidate_detail(entity: str, record_id: Any, cache_api=None) -> None:
    """
    Optional hard delete for the CURRENT versioned detail key.
    Use rarely; bump_detail is usually enough (and cheaper).
    """
    v = get_version(detail_version_key(entity, record_id))
    key = build_detail_cache_key(entity, record_id, v)
    log.info("🔥 DETAIL CACHE INVALIDATE key=%s", key)
    cache_api.delete_key(key)

def bump_user_profile(user_id: int) -> int:
    v = bump_version(user_profile_version_key(user_id))
    log.info("[cache] bump user_profile user_id=%s -> v%s", user_id, v)
    return v

def _bump(module_name: str, entity_name: str, scope_key: str) -> int:
    ve = f"{module_name}:{entity_name}:scope:{scope_key}"
    v = bump_version(list_version_key(ve, company_id=None))
    log.info("[cache] BUMP LIST %s -> v%s", ve, v)
    return v

def bump_list_cache_with_context(module_name: str, entity_name: str, context: AffiliationContext, *, params: dict) -> int:
    """
    Align write invalidation with the *same* scope logic the read path used for this request.
    Use this when your write has the same filter params (company_id/branch_id) available.
    """
    cfg = get_list_config(module_name, entity_name)
    scope_key = build_list_scope_key(cfg, context, params=params)
    return _bump(module_name, entity_name, scope_key)

# ----- explicit, resource-targeted invalidators -----
def bump_list_cache_global(module_name: str, entity_name: str) -> int:
    return _bump(module_name, entity_name, "global")

def bump_list_cache_company(module_name: str, entity_name: str, company_id: int) -> int:
    scope_key = f"co:{int(company_id)}"
    return _bump(module_name, entity_name, scope_key)

def bump_list_cache_branch(module_name: str, entity_name: str, company_id: int, branch_id: int) -> int:
    scope_key = f"br:{int(company_id)}-{int(branch_id)}"
    return _bump(module_name, entity_name, scope_key)



def bump_list_cache(module_name: str, entity_name: str, context: AffiliationContext) -> int:
    """
    Intelligently bump the version for a list, using the same scope logic as reads.
    """
    try:
        cfg = get_list_config(module_name, entity_name)
        scope_key = build_list_scope_key(cfg, context)
        ve = f"{module_name}:{entity_name}:scope:{scope_key}"
        v = bump_version(list_version_key(ve, company_id=None))
        log.info("[cache] BUMP LIST %s -> v%s", ve, v)
        return v
    except Exception as e:
        log.error("bump_list_cache failed for %s:%s err=%s", module_name, entity_name, e)
        return 0



# --- Dropdown invalidators (reuse list versioning) -----------------------------
def _bump_dropdown(module_name: str, name: str, scope_key: str) -> int:
    ve = f"{module_name}:{name}:scope:{scope_key}"
    v = bump_version(list_version_key(ve, company_id=None))
    log.info("[cache] BUMP DROPDOWN %s -> v%s", ve, v)
    return v

def bump_dropdown_global(module_name: str, name: str) -> int:
    return _bump_dropdown(module_name, name, "global")

def bump_dropdown_company(module_name: str, name: str, company_id: int) -> int:
    return _bump_dropdown(module_name, name, f"co:{int(company_id)}")

def bump_dropdown_branch(module_name: str, name: str, company_id: int, branch_id: int) -> int:
    return _bump_dropdown(module_name, name, f"br:{int(company_id)}-{int(branch_id)}")