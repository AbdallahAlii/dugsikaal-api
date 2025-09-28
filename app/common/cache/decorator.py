# app/common/cache/decorator.py
from __future__ import annotations

import functools, hashlib, json, inspect
from typing import Any, Callable, Optional

from .core_cache import cache_get, cache_set

def _default_key_builder(fn: Callable, args: tuple, kwargs: dict) -> str:
    sig = inspect.signature(fn)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    as_json = json.dumps(bound.arguments, sort_keys=True, default=str, separators=(",", ":"))
    h = hashlib.sha256(as_json.encode("utf-8")).hexdigest()
    return f"fcache:{fn.__module__}.{fn.__qualname__}:{h}"

def redis_cache(*, ttl: int = 300, jitter: int = 60,
                key_builder: Optional[Callable[[Callable, tuple, dict], str]] = None):
    """
    Cache function results in Redis keyed by arguments (Frappe-like @redis_cache).
    """
    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (key_builder or _default_key_builder)(fn, args, kwargs)
            cached = cache_get(key)
            if cached is not None:
                return cached
            result = fn(*args, **kwargs)
            cache_set(key, result, ttl=ttl, jitter=jitter)
            return result
        return wrapper
    return decorator
