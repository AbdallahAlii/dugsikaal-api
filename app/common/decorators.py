# app/common/decorators.py
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional
import logging

from flask import request, jsonify
from config.redis_config import get_redis_kv

log = logging.getLogger(__name__)

# Small Lua to INCR and set TTL only when the key is new; returns [count, ttl]
# This avoids “sliding” window and doesn’t keep extending the TTL on each hit.
_LUA_INCR_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


def _client_ip() -> str:
    """
    Best-effort client IP extractor. Works fine behind proxies if your reverse proxy
    sets X-Forwarded-For / X-Real-IP correctly.
    """
    hdr = request.headers.get("X-Forwarded-For", "")
    if hdr:
        # take first IP in the chain
        ip = hdr.split(",")[0].strip()
        if ip:
            return ip
    ip = request.headers.get("X-Real-IP")
    if ip:
        return ip.strip()
    return (request.remote_addr or "unknown").strip()


def rate_limit(
    *,
    key_prefix: str = "rl",
    limit: int = 10,
    window: int = 60,
    include_username: bool = False,
) -> Callable:
    """
    Simple fixed-window rate limiter.

    - Uses Redis key: rl:{key_prefix}:{client_id}[:{username}]
    - `limit` requests per `window` seconds (fixed window).
    - Adds `Retry-After` header when blocked (HTTP 429).

    Recommended defaults:
      - login: limit=10, window=60
      - other write endpoints: limit=60, window=60
    """
    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            r = get_redis_kv()
            cid = _client_ip()

            # Optionally fold in a username to reduce username spraying from a single IP.
            uname_part = ""
            if include_username:
                try:
                    json_body = request.get_json(silent=True) or {}
                    uname = (json_body.get("username") or "").strip().lower()
                    if uname:
                        uname_part = f":u:{uname}"
                except Exception:
                    pass

            key = f"rl:{key_prefix}:{cid}{uname_part}"

            try:
                res = r.eval(_LUA_INCR_WITH_TTL, 1, key, str(int(window)))
                count, ttl = int(res[0]), int(res[1])

                if count > limit:
                    resp = jsonify({
                        "ok": False,
                        "message": "Too many requests. Please try again later."
                    })
                    # helpful for clients
                    if ttl > 0:
                        resp.headers["Retry-After"] = str(ttl)
                    return resp, 429
            except Exception:
                # Fail-open: if Redis is down, don’t block the request.
                log.exception("Rate limit check failed (key=%s). Allowing request.", key)

            return view_func(*args, **kwargs)
        return wrapper
    return decorator
