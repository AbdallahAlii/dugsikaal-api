# app/common/cache/hash_cache.py
from __future__ import annotations

import json, logging
from typing import Any, Optional

from config.redis_config import get_redis_kv
from .local_cache import get_local_cache

log = logging.getLogger(__name__)
r = get_redis_kv()

def hget_json(name: str, field: str) -> Optional[Any]:
    lc_key = f"hget:{name}:{field}"
    lc = get_local_cache()
    if lc_key in lc:
        return lc[lc_key]
    raw = r.hget(name, field)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        val = json.loads(raw)
        lc[lc_key] = val
        return val
    except Exception:
        return None

def hset_json(name: str, field: str, value: Any, *, ttl: int | None = None) -> None:
    try:
        payload = json.dumps(value, default=str)
        pipe = r.pipeline()
        pipe.hset(name, field, payload)
        if ttl is not None:
            pipe.expire(name, ttl)  # expiry applies to the hash key
        pipe.execute()
        get_local_cache()[f"hget:{name}:{field}"] = value
    except Exception as e:
        log.error("hset_json failed hash=%s field=%s err=%s", name, field, e)

def hdel(name: str, field: str) -> int:
    get_local_cache().pop(f"hget:{name}:{field}", None)
    return int(r.hdel(name, field) or 0)

def hclear(name: str) -> int:
    lc = get_local_cache()
    for k in list(lc.keys()):
        if k.startswith(f"hget:{name}:"):
            lc.pop(k, None)
    return int(r.delete(name) or 0)

