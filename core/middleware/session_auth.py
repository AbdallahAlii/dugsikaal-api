
# core/middleware/session_auth.py
import logging
from flask import g, session, request, abort
from app.auth.service.auth_service import AuthService
from app.common.cache.session_manager import get_cached_user_status, is_session_indexed, remove_session
from app.common.models.base import StatusEnum
from app.security.rbac_guards import attach_auth_context  # ✅ added

# Initialize the AuthService instance
_auth = AuthService()
log = logging.getLogger(__name__)

# List of public endpoints that don't need a session check
AUTH_WHITELIST = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/refresh",
}


def before_request_session_auth():
    """
    Middleware that performs all session and user authentication checks
    and loads the user profile for protected endpoints.
    """
    # Initialize current user as None for every new request
    g.current_user = None

    # ✅ Skip CORS preflight. OPTIONS usually has no cookies.
    if request.method == "OPTIONS":
        return

    # Bypass auth for public endpoints
    if request.path in AUTH_WHITELIST:
        return

    # Log incoming request info
    log.info(f"--- Request to {request.path} ---")
    log.info(f"Flask session object before processing: {dict(session)}")

    # Check if user_id exists in session
    user_id = session.get("user_id")
    if not user_id:
        log.warning("User ID not found in session. User is anonymous. Aborting with 401.")
        # `require_login_globally` will handle the 401 response for protected endpoints
        return

    log.info(f"Found user_id '{user_id}' in session. Performing security checks...")

    try:
        # --- HARD GATE 1: Check cached account status ---
        cached_status = get_cached_user_status(user_id)
        if cached_status and cached_status != StatusEnum.ACTIVE.value:
            log.warning(f"User {user_id} is not active. Clearing session.")
            session.clear()
            # It's better to use abort(403) for account status issues
            abort(403, description="Your account is locked.")

        # --- HARD GATE 2: Check session indexing ---
        if not is_session_indexed(user_id):
            log.warning(f"Session for user {user_id} is not indexed. Invalid session or timing issue.")
            # Do NOT remove the session from Redis here, as it might be a temporary
            # state right after login. Just clear the browser session and force a re-login.
            session.clear()
            abort(401, description="Invalid session. Please log in again.")

        # --- FINAL STEP: Load user profile from cache (only if checks pass) ---
        prof = _auth.get_cached_profile(int(user_id))

        if prof and prof.get("ok"):
            g.current_user = prof.get("profile")
            # ✅ Attach RBAC affiliation/permission context for downstream guards (non-fatal)
            try:
                attach_auth_context(int(user_id))
            except Exception as e:
                log.warning(f"attach_auth_context failed for user {user_id}: {e}", exc_info=True)

            log.info(f"✅ Successfully loaded profile for user {user_id} into g.current_user.")
        else:
            log.warning(f"Could not retrieve profile for user {user_id}. Profile is invalid. Clearing session.")
            session.clear()  # Clear session if profile is invalid
            abort(401, description="Session expired or invalid. Please log in again.")

    except Exception as e:
        log.error(f"An exception occurred during authentication for {user_id}: {e}", exc_info=True)
        session.clear()
        abort(500)
