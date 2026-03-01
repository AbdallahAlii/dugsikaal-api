# app/common/cache/invalidation.py
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from app.common.cache.cache import bump_version
from app.common.cache import keys

from app.security.rbac_effective import AffiliationContext

from app.application_doctypes.core_lists.config import get_list_config
from app.application_doctypes.core_lists.cache import build_list_scope_key

from app.application_doctypes.core_dropdowns.config import get_dropdown_config
from app.application_doctypes.core_dropdowns.cache import build_dropdown_scope_key

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Low-level primitives (stable)
# ---------------------------------------------------------------------

def bump_detail(entity: str, record_id: Any) -> int:
    """Invalidate a single-record cache namespace (detail view)."""
    v = bump_version(keys.v_detail(entity, record_id))
    log.info("[cache] bump detail %s(%s) -> v%s", entity, record_id, v)
    return v


def bump_user_profile(user_id: int) -> int:
    """Invalidate cached user profile (RBAC changes, permissions, etc.)."""
    v = bump_version(keys.v_user_profile(user_id))
    log.info("[cache] bump user_profile %s -> v%s", user_id, v)
    return v


def bump_all() -> int:
    """Global epoch bump (admin-only / emergency)."""
    v = bump_version(keys.epoch_key())
    log.warning("[cache] bump ALL epoch -> e%s", v)
    return v


def _bump_list_scope(module_name: str, entity_name: str, scope_key: str) -> int:
    """
    Internal: bump the list version for "<module>:<entity>:scope:<scope_key>".
    This matches your list cache system exactly.
    """
    entity_scope = f"{module_name}:{entity_name}:scope:{scope_key}"
    v = bump_version(keys.v_list(entity_scope))
    log.info("[cache] bump list %s -> v%s", entity_scope, v)
    return v


def _bump_dropdown_scope(module_name: str, name: str, scope_key: str) -> int:
    """
    Internal: bump the dropdown version for "dropdown:<module>:<name>:scope:<scope_key>".
    """
    entity_scope = f"dropdown:{module_name}:{name}:scope:{scope_key}"
    v = bump_version(keys.v_list(entity_scope))
    log.info("[cache] bump dropdown %s -> v%s", entity_scope, v)
    return v


# ---------------------------------------------------------------------
# High-level helpers (what services should call)
#   ✅ These hide get_*_config + build_*_scope_key
#   ✅ No service should import core_lists/core_dropdowns modules anymore
# ---------------------------------------------------------------------

def bump_doctype_list_for_context(
    module_name: str,
    entity_name: str,
    context: AffiliationContext,
    *,
    # IMPORTANT: build_list_scope_key reads params["filters"]["company_id"/"branch_id"]
    filters: Optional[Mapping[str, Any]] = None,
) -> int:
    """
    Bump list cache for a doctype using the same scope logic as list reads.

    Your build_list_scope_key() prioritizes:
      1) params.filters.company_id / branch_id
      2) context.company_id / branch_id
      3) context.affiliations (hash fallback)

    For COMPANY-scoped doctypes, passing filters={"company_id": X} is enough.
    For BRANCH-scoped doctypes, pass filters={"company_id": X, "branch_id": Y}.
    """
    cfg = get_list_config(module_name, entity_name)
    params = {"filters": dict(filters or {})}
    scope_key = build_list_scope_key(cfg, context, params=params)
    return _bump_list_scope(module_name, entity_name, scope_key)


def bump_dropdown_for_context(
    module_name: str,
    name: str,
    context: AffiliationContext,
    *,
    # IMPORTANT: build_dropdown_scope_key reads params["company_id"/"branch_id"] (top-level)
    params: Optional[Mapping[str, Any]] = None,
) -> int:
    """
    Bump dropdown cache using the same scope logic as dropdown reads.

    Your build_dropdown_scope_key() prioritizes:
      1) params.company_id / branch_id
      2) context.company_id / branch_id
      3) context.affiliations fallback hash
    """
    cfg = get_dropdown_config(module_name, name)
    scope_key = build_dropdown_scope_key(cfg, context, params=dict(params or {}))
    return _bump_dropdown_scope(module_name, name, scope_key)


# ---------------------------------------------------------------------
# Optional convenience wrappers (nice for service readability)
# ---------------------------------------------------------------------

def bump_company_list(module_name: str, entity_name: str, context: AffiliationContext, company_id: int) -> int:
    """Explicit company list bump (works even if cfg scope changes later)."""
    return bump_doctype_list_for_context(module_name, entity_name, context, filters={"company_id": int(company_id)})


def bump_branch_list(module_name: str, entity_name: str, context: AffiliationContext, company_id: int, branch_id: int) -> int:
    """Explicit branch list bump (works even if cfg scope changes later)."""
    return bump_doctype_list_for_context(
        module_name,
        entity_name,
        context,
        filters={"company_id": int(company_id), "branch_id": int(branch_id)},
    )