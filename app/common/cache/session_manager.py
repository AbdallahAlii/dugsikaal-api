# app/common/cache/session_manager.py
from __future__ import annotations
from typing import Optional, List
from flask import session, request, current_app
from config.redis_config import get_redis_kv

r = get_redis_kv()

SESSION_INDEX_NS = "user_sessions"   # set of sids per user
USER_STATUS_NS   = "user_status"     # cached account status

def _k_index(user_id: int) -> str:
    return f"{SESSION_INDEX_NS}:{user_id}"

def _k_status(user_id: int) -> str:
    return f"{USER_STATUS_NS}:{user_id}"

def current_session_id() -> Optional[str]:
    # Flask-Session provides `session.sid` when server-side sessions are used
    sid = getattr(session, "sid", None)
    if sid:
        return sid
    cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    return request.cookies.get(cookie_name)

def index_current_session(user_id: int) -> None:
    sid = current_session_id()
    if sid:
        r.sadd(_k_index(user_id), sid)

def deindex_current_session(user_id: int) -> None:
    sid = current_session_id()
    if sid:
        r.srem(_k_index(user_id), sid)

def list_user_session_ids(user_id: int) -> List[str]:
    vals = r.smembers(_k_index(user_id)) or set()
    return [v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v) for v in vals]

def revoke_all_user_sessions(user_id: int) -> int:
    """
    Deletes all Flask-Session payloads for the user and clears the index.
    Uses SESSION_KEY_PREFIX from your config (e.g., 'erp_session:').
    """
    prefix = current_app.config.get("SESSION_KEY_PREFIX", "")
    deleted = 0
    for sid in list_user_session_ids(user_id):
        payload_key = f"{prefix}{sid}" if prefix else sid
        deleted += int(r.delete(payload_key) or 0)
    r.delete(_k_index(user_id))
    return deleted

def set_cached_user_status(user_id: int, status_value: str) -> None:
    r.set(_k_status(user_id), status_value)

def get_cached_user_status(user_id: int) -> Optional[str]:
    v = r.get(_k_status(user_id))
    if v is None:
        return None
    return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
def is_session_indexed(user_id: int) -> bool:
    """Checks if the current session ID is in the user's index set."""
    sid = current_session_id()
    if not sid:
        return False
    return r.sismember(_k_index(user_id), sid)


def remove_session(user_id: int) -> None:
    """
    Deletes the current session payload from Redis and removes it from the user's index.
    This is for explicit, single-session logout actions.
    """
    sid = current_session_id()
    if sid:
        prefix = current_app.config.get("SESSION_KEY_PREFIX", "")
        payload_key = f"{prefix}{sid}"
        r.delete(payload_key)  # Delete the session payload
        r.srem(_k_index(user_id), sid) # Remove from the user's index set