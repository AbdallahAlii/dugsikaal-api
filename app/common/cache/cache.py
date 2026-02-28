# # app/common/cache/cache.py

from __future__ import annotations

import json, random, logging
from typing import Any, Callable, Optional, Mapping

from config.redis_config import get_redis_kv
from .cache_keys import (
    global_epoch_key,
    detail_version_key, list_version_key, user_profile_version_key,
    build_detail_cache_key, build_list_cache_key, build_user_profile_cache_key,
)

log = logging.getLogger(__name__)
r = get_redis_kv()

# -------- low-level JSON helpers --------
def cache_get(key: str) -> Optional[Any]:
    raw = r.get(key)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None

def cache_set(key: str, value: Any, *, ttl: int = 3600, jitter: int = 120) -> None:
    try:
        payload = json.dumps(value, default=str)
        r.setex(key, ttl + random.randint(0, jitter), payload)
    except Exception as e:
        log.error("cache_set failed key=%s err=%s", key, e)

# -------- version helpers --------
def get_version(vkey: str, default: int = 1) -> int:
    v = r.get(vkey)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

def bump_version(vkey: str) -> int:
    try:
        return int(r.incr(vkey))
    except Exception as e:
        log.error("bump_version failed vkey=%s err=%s", vkey, e)
        return 0

def _epoch() -> int:
    # If never set, epoch defaults to 1
    return get_version(global_epoch_key(), default=1)

# -------- high-level read-through helpers --------
def get_or_build_detail(entity: str, record_id: Any, builder: Callable[[], Any], *, ttl: int = 300) -> Any:
    epoch = _epoch()
    v = get_version(detail_version_key(entity, record_id))
    key = build_detail_cache_key(entity, record_id, v, epoch)
    cached = cache_get(key)
    if cached is not None:
        return cached
    data = builder()
    cache_set(key, data, ttl=ttl)
    return data

def get_or_build_list(
    entity: str,
    *,
    company_id: Optional[int] = None,
    params: Optional[Mapping[str, Any]] = None,
    builder: Callable[[], Any],
    ttl: int = 120,
) -> Any:
    epoch = _epoch()
    v = get_version(list_version_key(entity, company_id))
    key = build_list_cache_key(entity, v, epoch, company_id=company_id, params=params or {})
    cached = cache_get(key)
    if cached is not None:
        return cached
    data = builder()
    cache_set(key, data, ttl=ttl)
    return data

def get_or_build_user_profile(user_id: int, builder: Callable[[], Any], *, ttl: int = 10800) -> Any:
    epoch = _epoch()
    v = get_version(user_profile_version_key(user_id))
    key = build_user_profile_cache_key(user_id, v, epoch)
    cached = cache_get(key)
    if cached is not None:
        return cached
    data = builder()
    cache_set(key, data, ttl=ttl)
    return data
