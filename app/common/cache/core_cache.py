# app/common/cache/core_cache.py
from __future__ import annotations

import json, random, logging
from typing import Any, Optional

from config.redis_config import get_redis_kv
from .local_cache import get_local_cache

log = logging.getLogger(__name__)
r = get_redis_kv()

# -------- Simple KV JSON helpers with per-request cache --------
def cache_get(key: str) -> Optional[Any]:
    lc = get_local_cache()
    if key in lc:
        return lc[key]
    raw = r.get(key)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        val = json.loads(raw)
        lc[key] = val  # warm per-request cache
        return val
    except Exception:
        return None

def cache_set(key: str, value: Any, *, ttl: int = 3600, jitter: int = 120) -> None:
    try:
        payload = json.dumps(value, default=str)
        r.setex(key, ttl + random.randint(0, jitter), payload)
        get_local_cache()[key] = value
    except Exception as e:
        log.error("cache_set failed key=%s err=%s", key, e)

# -------- Version helpers --------
def get_version(vkey: str, default: int = 1) -> int:
    v = r.get(vkey)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

# def bump_version(vkey: str) -> int:
#     try:
#         return int(r.incr(vkey))
#     except Exception as e:
#         log.error("bump_version failed vkey=%s err=%s", vkey, e)  # fixed arg order
#         return 0
def bump_version(vkey: str) -> int:
    try:
        n = int(r.incr(vkey))
        # If key was missing, INCR returns 1 which doesn't invalidate when default=1.
        if n == 1:
            n = int(r.incr(vkey))  # make it 2
        return n
    except Exception as e:
        log.error("bump_version failed vkey=%s err=%s", vkey, e)
        return 0
