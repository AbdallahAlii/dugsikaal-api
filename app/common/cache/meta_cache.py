# app/common/cache/meta_cache.py
from __future__ import annotations
from typing import Optional
from .hash_cache import hget_json, hset_json, hdel, hclear

META_HASH = "meta"

def get_cached_meta(entity: str, builder) -> dict:
    val = hget_json(META_HASH, entity)
    if val is not None:
        return val
    meta = builder()
    hset_json(META_HASH, entity, meta, ttl=24*3600)
    return meta

def clear_cached_meta(entity: Optional[str] = None):
    if entity:
        hdel(META_HASH, entity)
    else:
        hclear(META_HASH)
