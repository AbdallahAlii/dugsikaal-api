from __future__ import annotations
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from config.database import db
from app.auth.models.users import User, UserAffiliation, UserType


class AuthRepository:
    """
    Thin repository for user queries. Keep business logic in the service.
    """

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Fetch user by username (case-insensitive match).
        """
        if not username:
            return None
        u = username.strip()
        stmt = (
            select(User)
            .options(
                joinedload(User.affiliations).joinedload(UserAffiliation.user_type),
                joinedload(User.affiliations).joinedload(UserAffiliation.company),
                joinedload(User.affiliations).joinedload(UserAffiliation.branch),
            )
            .where(func.lower(User.username) == func.lower(u))
        )
        return db.session.scalar(stmt)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        stmt = (
            select(User)
            .options(
                joinedload(User.affiliations).joinedload(UserAffiliation.user_type),
                joinedload(User.affiliations).joinedload(UserAffiliation.company),
                joinedload(User.affiliations).joinedload(UserAffiliation.branch),
            )
            .where(User.id == user_id)
        )
        return db.session.scalar(stmt)

    def update_last_login(self, user: User) -> None:
        from datetime import datetime, timezone
        user.last_login = datetime.now(timezone.utc)
        # commit controlled by service
