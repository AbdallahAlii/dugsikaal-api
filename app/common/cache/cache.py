# app/common/cache/cache.py
from __future__ import annotations
import json, time, random, logging, functools, inspect, hashlib
from typing import Any, Callable, Optional, Mapping

from .redis_client import redis_kv
from .local_cache import get_local_cache
from . import keys

log = logging.getLogger(__name__)

def _jitter(ttl: int, jitter: int) -> int:
    return ttl + (random.randint(0, jitter) if jitter else 0)

# -------- JSON KV with per-request cache --------
def get_json(key: str) -> Optional[Any]:
    lc = get_local_cache()
    if key in lc:
        return lc[key]

    raw = redis_kv.get(key)
    if not raw:
        return None
    try:
        val = json.loads(raw)
        lc[key] = val
        return val
    except Exception:
        return None

def set_json(key: str, value: Any, *, ttl: int, jitter: int = 120) -> None:
    try:
        payload = json.dumps(value, default=str)
    except Exception:
        # if serialization fails, don't cache
        return

    ok = redis_kv.setex(key, _jitter(ttl, jitter), payload)
    if ok:
        get_local_cache()[key] = value

def delete(key: str) -> None:
    redis_kv.delete(key)
    get_local_cache().pop(key, None)

# -------- version helpers (safe) --------
def get_version(vkey: str, default: int = 1) -> int:
    raw = redis_kv.get(vkey)
    try:
        return int(raw) if raw is not None else default
    except Exception:
        return default

def bump_version(vkey: str) -> int:
    n = redis_kv.incr(vkey)
    # if redis down -> n=0, that's fine (we treat as best-effort)
    if n == 1:
        # avoid default=1 collision
        n = redis_kv.incr(vkey)
    return n

def get_epoch() -> int:
    return get_version(keys.epoch_key(), default=1)

# -------- read-through helpers --------
def get_or_build_detail(entity: str, record_id: Any, builder: Callable[[], Any], *, ttl: int = 300) -> Any:
    epoch = get_epoch()
    v = get_version(keys.v_detail(entity, record_id), default=1)
    ck = keys.k_detail(entity, record_id, epoch=epoch, version=v)

    cached = get_json(ck)
    if cached is not None:
        return cached

    data = builder()
    if data is not None:
        set_json(ck, data, ttl=ttl)
    return data

def get_or_build_list(entity_scope: str, params: Mapping[str, Any], builder: Callable[[], Any], *, ttl: int = 120) -> Any:
    epoch = get_epoch()
    v = get_version(keys.v_list(entity_scope), default=1)
    ck = keys.k_list(entity_scope, epoch=epoch, version=v, params=params)

    cached = get_json(ck)
    if cached is not None:
        return cached

    data = builder()
    set_json(ck, data, ttl=ttl)
    return data

def get_or_build_user_profile(user_id: int, builder: Callable[[], Any], *, ttl: int = 3 * 3600) -> Any:
    epoch = get_epoch()
    v = get_version(keys.v_user_profile(user_id), default=1)
    ck = keys.k_user_profile(user_id, epoch=epoch, version=v)

    cached = get_json(ck)
    if cached is not None:
        return cached

    data = builder()
    if data is not None:
        set_json(ck, data, ttl=ttl)
    return data

# -------- decorator (optional) --------
def redis_cache(*, ttl: int = 300, jitter: int = 60, key_builder: Optional[Callable] = None):
    def _default_key_builder(fn: Callable, args: tuple, kwargs: dict) -> str:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        as_json = json.dumps(bound.arguments, sort_keys=True, default=str, separators=(",", ":"))
        h = hashlib.sha256(as_json.encode("utf-8")).hexdigest()
        return f"fcache:{fn.__module__}.{fn.__qualname__}:{h}"

    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            k = (key_builder or _default_key_builder)(fn, args, kwargs)
            cached = get_json(k)
            if cached is not None:
                return cached
            out = fn(*args, **kwargs)
            set_json(k, out, ttl=ttl, jitter=jitter)
            return out
        return wrapper
    return deco