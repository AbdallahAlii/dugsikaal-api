# app/common/decorators.py
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Callable

from flask import request, jsonify
from app.common.cache.redis_client import redis_kv

log = logging.getLogger(__name__)


def _client_ip() -> str:
    """
    Best-effort client IP extractor. Works behind proxies if they set
    X-Forwarded-For / X-Real-IP correctly.
    """
    hdr = request.headers.get("X-Forwarded-For", "")
    if hdr:
        ip = hdr.split(",")[0].strip()
        if ip:
            return ip
    ip = request.headers.get("X-Real-IP")
    if ip:
        return ip.strip()
    return (request.remote_addr or "unknown").strip()


def _bucket_key(*, key_prefix: str, client_id: str, username: str, window: int) -> tuple[str, int]:
    """
    Fixed window bucket key:
      rl:<prefix>:<client>:u:<username>:<bucket>
    TTL is the remaining seconds in current window.
    """
    now = int(time.time())
    bucket = now // int(window)
    ttl = int(window) - (now % int(window))
    uname_part = f":u:{username}" if username else ""
    key = f"rl:{key_prefix}:{client_id}{uname_part}:{bucket}"
    return key, ttl


def rate_limit(
    *,
    key_prefix: str = "rl",
    limit: int = 10,
    window: int = 60,
    include_username: bool = False,
) -> Callable:
    """
    Fixed-window rate limiter (Redis optional; fail-open).

    - Key is bucketed by time => no sliding window.
    - TTL is set to the remaining seconds in the bucket.
    - If Redis is down, request is allowed (fail-open).
    - Adds Retry-After on 429.

    Recommended:
      - login: limit=10, window=60, include_username=True
      - write endpoints: limit=60, window=60
    """
    def decorator(view_func: Callable):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            cid = _client_ip()

            uname = ""
            if include_username:
                try:
                    json_body = request.get_json(silent=True) or {}
                    uname = (json_body.get("username") or "").strip().lower()
                except Exception:
                    uname = ""

            key, ttl = _bucket_key(
                key_prefix=key_prefix,
                client_id=cid,
                username=uname,
                window=window,
            )

            try:
                # Best-effort: if Redis is down, these return 0/False and we allow.
                count = redis_kv.incr(key)

                # If key is new (count == 1), set expiry to window remainder.
                # If expire fails, we still proceed (worst case: key persists longer).
                if count == 1 and ttl > 0:
                    redis_kv.expire(key, ttl)

                if count > int(limit):
                    resp = jsonify({"ok": False, "message": "Too many requests. Please try again later."})
                    if ttl > 0:
                        resp.headers["Retry-After"] = str(ttl)
                    return resp, 429

            except Exception:
                # Fail-open: do not block if limiter fails
                log.exception("Rate limit check failed (key=%s). Allowing request.", key)

            return view_func(*args, **kwargs)
        return wrapper
    return decorator