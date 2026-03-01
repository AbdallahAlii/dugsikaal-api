
# app/auth/service/auth_service.py
from __future__ import annotations

import logging
from typing import Tuple, Dict, Any, Optional
from flask import session
from sqlalchemy.exc import SQLAlchemyError

from config.database import db
from app.auth.repo.user_repo import AuthRepository
from app.common.models.base import StatusEnum
from app.common.security.passwords import verify_password
from app.common.cache.cache import get_or_build_user_profile
from app.common.cache.invalidation import bump_user_profile
from app.common.cache.session_manager import index_current_session, set_cached_user_status, remove_session

# Import the RBAC calculator
from app.security.effective_permissions import get_effective_permissions_from_db

log = logging.getLogger(__name__)


class AuthService:
    def __init__(self, repo: Optional[AuthRepository] = None):
        self.repo = repo or AuthRepository()

    def login(self, username: str, password: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Handles user login, validation, and session setup."""
        user = self.repo.get_user_by_username(username)
        log.info(f"Attempting login for user: {username}")

        if not user or not verify_password(password, user.password_hash):
            return False, "Username or password is incorrect.", None

        if user.status != StatusEnum.ACTIVE:
            return False, "Your account is inactive. Please contact the administrator.", None

        try:
            self.repo.update_last_login(user)
            db.session.commit()
            log.info(f"✅ Login successful for user '{username}'")
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error(f"A database error occurred during login for user {user.username}: {e}")
            return False, "A database error occurred during login.", None

        # Invalidate any old cached profile version to force a refresh
        bump_user_profile(user.id)

        # Build and cache a fresh, complete user profile
        profile_wrap = self.get_cached_profile(user.id)
        if not profile_wrap.get("ok"):
            return False, profile_wrap.get("message", "Profile error."), None
        profile = profile_wrap["profile"]

        # Set minimal session data for authentication middleware
        session.clear()
        session["user_id"] = user.id
        session.permanent = True
        log.info(f"✅ Flask session set for user: {user.id}")

        # Index session and cache live status (best-effort)
        try:
            index_current_session(user.id)
            set_cached_user_status(user.id, user.status.value)
        except Exception:
            log.warning("Failed to index session or set user status in Redis.", exc_info=True)

        return True, "Login successful.", profile

    def logout(self) -> Tuple[bool, str]:
        """Logs out the current user and clears the session."""
        uid = session.get("user_id")
        if uid:
            try:
                remove_session(int(uid))
                log.info(f"User {uid} session removed from Redis.")
            except Exception:
                log.warning("Failed to remove session from Redis.", exc_info=True)

        session.clear()
        return True, "Logout successful."

    def build_user_profile_dict(self, user_id: int) -> Dict[str, Any]:
        """
        Builds a comprehensive user profile dictionary for caching, including RBAC data.
        """
        user = self.repo.get_user_by_id(user_id)
        if not user:
            return {"ok": False, "message": "User not found"}

        affiliations = [
            {
                "id": a.id, "company_id": a.company_id, "branch_id": a.branch_id,
                "user_type_id": a.user_type_id, "user_type": (a.user_type.name if a.user_type else None),
                "is_primary": a.is_primary, "linked_entity_id": a.linked_entity_id,
            }
            for a in user.affiliations
        ]

        # FIX: Correctly unpack the tuple and initialize defaults
        permissions_list = []
        role_names = []
        is_system_admin = False
        try:
            # FIX: Unpack the returned tuple into three distinct variables
            permissions_set, roles, is_admin = get_effective_permissions_from_db(
                user_id=user.id, db=db.session
            )

            # Use the unpacked variables correctly
            permissions_list = list(permissions_set)
            role_names = roles
            is_system_admin = is_admin

        except Exception:
            log.exception(f"Failed to compute effective permissions for user {user_id}")
            # Ensure defaults are set on failure
            permissions_list = []
            role_names = []
            is_system_admin = False

        return {
            "ok": True,
            "profile": {
                "user_id": user.id,
                "username": user.username,
                "status": user.status.value,
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "created_at": user.created_at.isoformat(),
                "updated_at": user.updated_at.isoformat(),
                "affiliations": affiliations,
                # NEW: Surface all the rich RBAC data in the profile
                "permissions": permissions_list,
                "roles": role_names,
                "is_system_admin": is_system_admin,
            },
        }

    def get_cached_profile(self, user_id: int) -> Dict[str, Any]:
        """
        Fetches the user's profile from the Redis cache, or builds it if not found.
        """
        return get_or_build_user_profile(
            user_id=user_id,
            builder=lambda: self.build_user_profile_dict(user_id),
            ttl=3 * 3600,
        )

    def logout(self) -> Tuple[bool, str]:
        """Logs out the current user and clears the session."""
        uid = session.get("user_id")
        if uid:
            try:
                remove_session(int(uid))
                log.info("User %s session removed from external store.", uid)
            except Exception:
                log.warning("Failed to remove session from external store.", exc_info=True)

        # Always clear Flask session too (route also clears — double-safe is fine)
        session.clear()
        session.permanent = False
        return True, "Logout successful."