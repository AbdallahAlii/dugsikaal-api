# auth/serivce/user_service
from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import NotFound, Unauthorized, BadRequest

from config.database import db
from app.auth.repo.user_repo import AuthRepository
from app.auth.models.users import User
from app.common.models.base import StatusEnum
from app.common.security.passwords import hash_password, verify_password
from app.common.security.password_rules import ensure_password_ok
from app.common.cache.cache_invalidator import bump_user_profile
from app.common.cache.session_manager import remove_session, set_cached_user_status
from app.security.rbac_guards import ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


def _resolve_target_scope(user: User) -> Tuple[Optional[int], Optional[int]]:
    """Get (company_id, branch_id) from the target user's primary affiliation (or first)."""
    if not user or not user.affiliations:
        return None, None
    primary = next((a for a in user.affiliations if getattr(a, "is_primary", False)), None)
    picked = primary or user.affiliations[0]
    return picked.company_id, picked.branch_id


class UserService:
    def __init__(self, repo: Optional[AuthRepository] = None):
        self.repo = repo or AuthRepository()

    # Self-service: change my password
    def change_my_password_service(self, user_id: int, old_password: str, new_password: str) -> str:
        user = self.repo.get_user_by_id(user_id)
        if not user:
            raise NotFound("User not found.")

        if not verify_password(old_password, user.password_hash):
            raise Unauthorized("Incorrect old password.")

        # Friendly, strong rules (raises 422 via ensure_password_ok if invalid)
        ensure_password_ok(new_password)

        try:
            user.password_hash = hash_password(new_password)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error changing password for user %s: %s", user_id, e)
            raise BadRequest("Failed to change password due to a server error.")

        # best-effort cache/session hooks
        try:
            bump_user_profile(user.id)
            remove_session(user.id)
        except Exception:
            log.exception("Post-change hooks failed for user_id=%s", user.id)

        return "Password updated successfully."

    # Admin: reset another user's password (company/branch scoped)
    def reset_user_password_service(self, target_user_id: int, new_password: str, context: AffiliationContext) -> str:
        target = self.repo.get_user_by_id(target_user_id)
        if not target:
            raise NotFound("User not found.")

        company_id, branch_id = _resolve_target_scope(target)
        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        ensure_password_ok(new_password)

        try:
            target.password_hash = hash_password(new_password)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error resetting password for user %s: %s", target_user_id, e)
            raise BadRequest("Failed to reset password due to a server error.")

        try:
            bump_user_profile(target.id)
            remove_session(target.id)
        except Exception:
            log.exception("Post-reset hooks failed for user_id=%s", target.id)

        return "Password reset successfully."

    # Admin: update account status (company/branch scoped)
    def update_account_status_service(self, target_user_id: int, new_status: str, context: AffiliationContext) -> str:
        target = self.repo.get_user_by_id(target_user_id)
        if not target:
            raise NotFound("User not found.")

        company_id, branch_id = _resolve_target_scope(target)
        ensure_scope_by_ids(context=context, target_company_id=company_id, target_branch_id=branch_id)

        try:
            status_enum = StatusEnum(new_status)
        except ValueError:
            allowed = ", ".join([s.value for s in StatusEnum])
            raise BadRequest(f"Invalid status: {new_status}. Must be one of: {allowed}")

        try:
            target.status = status_enum
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            log.error("DB error updating status for user %s: %s", target_user_id, e)
            raise BadRequest("Failed to update account status due to a server error.")

        try:
            bump_user_profile(target.id)
            set_cached_user_status(target.id, target.status.value)
            if status_enum == StatusEnum.INACTIVE:
                remove_session(target.id)
        except Exception:
            log.exception("Post-status hooks failed for user_id=%s", target.id)

        return "Account status updated successfully."
