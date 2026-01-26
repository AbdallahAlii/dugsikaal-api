
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import (
    selectinload,
    joinedload,
    load_only,
    noload,
)

from config.database import db
from app.auth.models.users import User, UserAffiliation, UserType
from app.application_org.models.company import Company, Branch  # adjust import path if different


class AuthRepository:
    """
    Auth data access (ERP-style):
    - Login loads ONLY what is required for auth + scope.
    - No heavy tenant graphs (Company.* collections) are loaded here.
    """

    # ---- loader bundles -------------------------------------------------

    @staticmethod
    def _login_load_options():
        """
        Options optimized for login/auth/me endpoints:
        - User + affiliations
        - Minimal UserType / Company / Branch fields
        - Block all deep relationships under Company/Branch
        """
        return (
            # Load affiliations via selectin (avoids big JOIN row multiplication)
            selectinload(User.affiliations)
            .options(
                # affiliation.user_type (small table) - load minimal
                joinedload(UserAffiliation.user_type).load_only(
                    UserType.id,
                    UserType.name,
                    UserType.status,
                ),

                # affiliation.company - load minimal + block graph
                joinedload(UserAffiliation.company)
                .options(
                    load_only(
                        Company.id,
                        Company.name,
                        Company.prefix,
                        Company.timezone,
                        Company.status,
                    ),
                    noload("*"),  # IMPORTANT: stops Company -> branches/programs/etc
                ),

                # affiliation.branch - load minimal + block graph
                joinedload(UserAffiliation.branch)
                .options(
                    load_only(
                        Branch.id,
                        Branch.name,
                        Branch.code,
                        Branch.company_id,
                        Branch.status,
                    ),
                    noload("*"),  # stops Branch -> other relationships
                ),
            ),
        )

    # ---- queries --------------------------------------------------------

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Fetch user by username (case-insensitive).
        Login-safe, does not load company graph.
        """
        if not username:
            return None

        u = username.strip()

        stmt = (
            select(User)
            .options(*self._login_load_options())
            .where(func.lower(User.username) == func.lower(u))
        )
        return db.session.scalar(stmt)

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        Fetch user by id.
        Same optimized loading as login.
        """
        stmt = (
            select(User)
            .options(*self._login_load_options())
            .where(User.id == user_id)
        )
        return db.session.scalar(stmt)

    def update_last_login(self, user: User) -> None:
        """
        Update last_login timestamp (commit handled by service).
        """
        from datetime import datetime, timezone

        user.last_login = datetime.now(timezone.utc)
