# app/auth/deps.py
import logging
from typing import Dict, Any, Optional
from flask import g, session, abort
from app.auth.service.auth_service import AuthService
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


def get_current_user() -> Dict[str, Any]:
    """
    Retrieves the current user's profile from the session and cache.
    This function acts as a dependency for route handlers.
    """
    user_id = session.get("user_id")

    if not user_id:
        log.warning("get_current_user: User ID not found in session. Aborting with 401.")
        abort(401)  # Flask's way of returning 401

    try:
        # Load user profile from cache via AuthService
        _auth = AuthService()
        prof = _auth.get_cached_profile(int(user_id))

        if not prof or not prof.get("ok"):
            log.warning(f"get_current_user: Could not retrieve profile for user {user_id}. Aborting with 401.")
            session.clear()
            abort(401, description="Session expired or invalid. Please log in again.")

        g.current_user = prof.get("profile")
        return g.current_user

    except Exception as e:
        log.error(f"An exception occurred loading profile for {user_id}: {e}", exc_info=True)
        session.clear()
        abort(500)


