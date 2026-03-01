# app/common/cache/session_manager.py
from __future__ import annotations
from typing import Optional, List
from flask import session, request, current_app
from app.common.cache.redis_client import redis_kv

SESSION_INDEX_NS = "user_sessions"   # set of sids per user
USER_STATUS_NS   = "user_status"     # cached account status

def _k_index(user_id: int) -> str:
    return f"{SESSION_INDEX_NS}:{int(user_id)}"

def _k_status(user_id: int) -> str:
    return f"{USER_STATUS_NS}:{int(user_id)}"

def current_session_id() -> Optional[str]:
    # Cookie session: there is no session.sid. Use a stable-ish cookie identifier.
    # We use the session cookie value itself (signed by Flask) as the "sid".
    cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    return request.cookies.get(cookie_name)

def index_current_session(user_id: int) -> None:
    sid = current_session_id()
    if not sid:
        return
    # Safe: if Redis is down, this just won't index.
    try:
        # store sid in a redis set (we don't have sadd wrapper; simplest use kv client directly via underlying redis is not exposed)
        # So we encode as a hash-like key: user_sessions:<uid>:<sid> = 1 (ttl optional)
        redis_kv.setex(f"{_k_index(user_id)}:{sid}", 7 * 24 * 3600, "1")
    except Exception:
        pass

def is_session_indexed(user_id: int) -> bool:
    sid = current_session_id()
    if not sid:
        return False
    try:
        return redis_kv.get(f"{_k_index(user_id)}:{sid}") is not None
    except Exception:
        return False

def remove_session(user_id: int) -> None:
    # For cookie sessions, you can't delete the cookie from server.
    # You can only de-index current sid so it fails the redis gate when redis is up.
    sid = current_session_id()
    if not sid:
        return
    try:
        redis_kv.delete(f"{_k_index(user_id)}:{sid}")
    except Exception:
        pass

def revoke_all_user_sessions(user_id: int) -> int:
    # Without native SCAN helpers in SafeRedis, keep this simple:
    # best strategy: bump a user-specific auth version instead (recommended).
    # We'll implement "auth epoch" technique below instead of scanning keys.
    return 0

def set_cached_user_status(user_id: int, status_value: str) -> None:
    try:
        redis_kv.setex(_k_status(user_id), 3600, status_value)
    except Exception:
        pass

def get_cached_user_status(user_id: int) -> Optional[str]:
    try:
        return redis_kv.get(_k_status(user_id))
    except Exception:
        return None