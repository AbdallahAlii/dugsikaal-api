# app/common/cache/api.py
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from config.redis_config import get_redis_kv
from .core_cache import cache_get, cache_set, get_version
from .cache_keys import list_version_key, build_list_cache_key, detail_version_key, build_detail_cache_key
from .hash_cache import hget_json, hset_json, hdel, hclear
from .decorator import redis_cache
from .local_cache import get_local_cache

log = logging.getLogger(__name__)
r = get_redis_kv()

# ---- Simple KV ----
def get(key: str) -> Optional[Any]:
    return cache_get(key)

def set(key: str, value: Any, ttl: int = 3600) -> None:
    cache_set(key, value, ttl=ttl)

def delete_key(key: str) -> None:
    try:
        r.delete(key)
        get_local_cache().pop(key, None)
    except Exception:
        pass

# ---- Redis Hash ----
def hget(hash_key: str, field: str) -> Optional[Any]:
    return hget_json(hash_key, field)

def hset(hash_key: str, field: str, value: Any, *, ttl: int | None = None) -> None:
    hset_json(hash_key, field, value, ttl=ttl)

def hdelete(hash_key: str, field: str) -> int:
    return hdel(hash_key, field)

def hclear_all(hash_key: str) -> int:
    return hclear(hash_key)

# ---- Doctype/List read-through (centralized key+version) ----
def get_doctype_list(
    *,
    module_name: str,
    entity_name: str,
    scope_key: str,                   # computed by scope builder
    params: Mapping[str, Any],        # page/per_page/sort/order/search/filters
    builder: Callable[[], Any],       # DB work on miss
    ttl: int = 300,
    enabled: bool = True,
) -> Any:
    if not enabled:
        return builder()

    ve = f"{module_name}:{entity_name}:scope:{scope_key}"
    v  = get_version(list_version_key(ve, company_id=None))
    final_key = build_list_cache_key(entity=ve, version=v, company_id=None, params=dict(params))

    cached = get(final_key)
    if cached is not None:
        log.info("✅ LIST CACHE HIT (%s)", final_key)
        return cached

    log.info("❌ LIST CACHE MISS (%s)", final_key)
    fresh = builder()
    set(final_key, fresh, ttl=ttl)
    return fresh

# ---- Doctype/Detail read-through (versioned, pairs with bump_detail) ----
def get_doctype_detail(
    *,
    module_name: str,
    entity_name: str,
    record_id: Any,
    builder: Callable[[], Any],
    ttl: int = 300,
    enabled: bool = True,
) -> Any:
    """
    Version-based detail cache (pairs with cache_invalidator.bump_detail).
    """
    if not enabled:
        data = builder()
        log.info("⚠️ DETAIL CACHE BYPASSED (%s:%s)", f"{module_name}:{entity_name}", record_id)
        return data

    entity = f"{module_name}:{entity_name}"
    v = get_version(detail_version_key(entity, record_id))
    key = build_detail_cache_key(entity, record_id, v)

    cached = get(key)
    if cached is not None:
        log.info("✅ DETAIL CACHE HIT (%s)", key)
        return cached

    log.info("❌ DETAIL CACHE MISS (%s)", key)
    data = builder()
    if data is not None:
        set(key, data, ttl=ttl)
    return data

def get_dropdown_options(
    *,
    module_name: str,
    name: str,
    scope_key: str,
    params: Mapping[str, Any],     # include q, limit, offset, filters, sort, order
    builder: Callable[[], Any],
    ttl: int = 600,
    enabled: bool = True,
) -> Any:
    """
    key => docdrop:<module>:<name>:scope:<scope>:v<version>:<hash(params)>
    Uses list_version_key so existing bump helpers can invalidate by scope.
    """
    if not enabled:
        return builder()

    ve = f"{module_name}:{name}:scope:{scope_key}"
    v  = get_version(list_version_key(ve, company_id=None))
    final_key = build_list_cache_key(entity=f"docdrop:{ve}", version=v, company_id=None, params=dict(params))

    cached = get(final_key)
    if cached is not None:
        log.info("✅ DROPDOWN CACHE HIT (%s)", final_key)
        return cached

    log.info("❌ DROPDOWN CACHE MISS (%s)", final_key)
    fresh = builder()
    set(final_key, fresh, ttl=ttl)
    return fresh


__all__ = [
    "get","set","delete_key",
    "hget","hset","hdelete","hclear_all",
    "get_doctype_list","redis_cache",
]
