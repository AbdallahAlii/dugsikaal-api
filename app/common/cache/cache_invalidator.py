# # # # app/common/cache/cache_invalidator.py

from __future__ import annotations

import logging
from typing import Any, Optional

from .cache import get_version
from .core_cache import bump_version
from .cache_keys import detail_version_key, list_version_key, user_profile_version_key, build_detail_cache_key, \
    price_list_version_key, coa_balance_version_key
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


def bump_stock_dropdowns(module_name: str, entity_name: str, company_id: int) -> None:
    """
    Bump all related dropdown caches for stock entities.
    This handles both main dropdowns and active_* dropdowns.
    """
    # Always bump the main dropdown
    bump_dropdown_company(module_name, entity_name, company_id)

    # Also bump active_* dropdown if it exists for stock entities
    if entity_name in ["warehouses"]:
        active_entity = f"active_{entity_name}"
        try:
            # Attempt to bump the 'active' list
            bump_dropdown_company(module_name, active_entity, company_id)
            log.debug("[cache] Also bumped %s:%s", module_name, active_entity)
        except Exception as e:
            # Log a warning but DO NOT FAIL the entire process if the secondary bump fails
            log.warning("[cache] Failed to bump %s:%s: %s", module_name, active_entity, e)

    log.info("[cache] BUMPED STOCK DROPDOWNS %s:%s -> company:%s", module_name, entity_name, company_id)
def bump_inventory_dropdowns(module_name: str, entity_name: str, company_id: int) -> None:
    """
    Bump all related dropdown caches for inventory entities.
    This handles both main dropdowns and active_* dropdowns.
    """
    # Always bump the main dropdown
    bump_dropdown_company(module_name, entity_name, company_id)

    # Also bump active_* dropdown if it exists for inventory entities
    if entity_name in ["items", "brands", "uoms"]:
        active_entity = f"active_{entity_name}"
        try:
            # Attempt to bump the 'active' list, which may not always exist or be strictly required
            bump_dropdown_company(module_name, active_entity, company_id)
            log.debug("[cache] Also bumped %s:%s", module_name, active_entity)
        except Exception as e:
            # Log a warning but DO NOT FAIL the entire process if the secondary bump fails
            log.warning("[cache] Failed to bump %s:%s: %s", module_name, active_entity, e)

    log.info("[cache] BUMPED INVENTORY DROPDOWNS %s:%s -> company:%s", module_name, entity_name, company_id)
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

def bump_price_list(company_id: int, price_list_id: int) -> int:
    """
    Bump version on any ItemPrice write for this company/price list.
    Readers will rebuild the per-day snapshot lazily on next access.
    """
    v = bump_version(price_list_version_key(company_id, price_list_id))
    log.info("[cache] BUMP PRICE LIST co=%s pl=%s -> v%s", company_id, price_list_id, v)
    return v


def bump_coa_structure_company(company_id: int) -> int:
    """
    Bumps the version used by the COA tree *structure* (code/name/parent/is_group changes).
    Call from Account create/update/delete that changes structure or label.
    """
    scope_key = f"co:{int(company_id)}"
    ve = f"accounting:coa_tree:scope:{scope_key}"
    v = bump_version(list_version_key(ve, company_id=None))
    log.info("[cache] BUMP COA STRUCT company=%s -> v%s", company_id, v)
    return v

def bump_coa_balance_company(company_id: int) -> int:
    """
    Bumps the version used by the COA *balances* (GL postings).
    Call after successful posting that changes AccountBalance/current_balance.
    """
    v = bump_version(coa_balance_version_key(company_id))
    log.info("[cache] BUMP COA BAL company=%s -> v%s", company_id, v)
    return v



# ─────────────────────────────────────────────────────────────
# Accounting-specific convenience bumpers (lists + details)
# ─────────────────────────────────────────────────────────────

# ---- generic detail bump (entity-only namespace in detail cache) ------------
def bump_accounting_detail(entity: str, record_id: int) -> int:
    """
    Bump the versioned detail cache for a single Accounting record.
    Readers use namespaced keys like 'accounting:<entity>'.
    """
    return bump_detail(f"accounting:{entity}", record_id)


# ---- Modes of Payment (company scope) ---------------------------------------
def bump_mop_list_company(company_id: int) -> int:
    return bump_list_cache_company("accounting", "modes_of_payment", company_id)

def bump_mop_detail(mop_id: int) -> int:
    return bump_accounting_detail("modes_of_payment", mop_id)

# ---- Fiscal Years (company scope) -------------------------------------------
def bump_fiscal_years_list_company(company_id: int) -> int:
    return bump_list_cache_company("accounting", "fiscal_years", company_id)

def bump_fiscal_year_detail(fiscal_year_id: int) -> int:
    return bump_accounting_detail("fiscal_years", fiscal_year_id)

# ---- Cost Centers (branch + company scope) ----------------------------------
def bump_cost_centers_list_company(company_id: int) -> int:
    return bump_list_cache_company("accounting", "cost_centers", company_id)

def bump_cost_centers_list_branch(company_id: int, branch_id: int) -> int:
    return bump_list_cache_branch("accounting", "cost_centers", company_id, branch_id)

def bump_cost_center_detail(cost_center_id: int) -> int:
    return bump_accounting_detail("cost_centers", cost_center_id)

# ---- Accounts (company scope) -----------------------------------------------
def bump_accounts_list_company(company_id: int) -> int:
    return bump_list_cache_company("accounting", "accounts", company_id)

def bump_account_detail(account_id: int) -> int:
    return bump_accounting_detail("accounts", account_id)


