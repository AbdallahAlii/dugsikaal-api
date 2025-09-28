from __future__ import annotations
from typing import Optional
from datetime import datetime

from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


class User(BaseModel):
    """
    Core user record. Keep it small: identity + auth + lifecycle.
    Status uses your global StatusEnum (ACTIVE/INACTIVE).
    """
    __tablename__ = "users"

    # identity
    username: Mapped[str] = mapped_column(db.String(150), unique=True, nullable=False, index=True)


    # auth
    password_hash: Mapped[str] = mapped_column(db.String(255), nullable=False)

    # lifecycle
    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="user_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True))

    # relationships (loaded when needed)
    affiliations = db.relationship(
        "UserAffiliation",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_users_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


class UserType(BaseModel):
    """
    High-level classification for a user in a given affiliation, e.g.:
    - 'staff'
    - 'student'
    - 'guardian'
    Keep both code and name for flexibility; code is a stable identifier.
    """
    __tablename__ = "user_types"


    name: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False)            # e.g. 'Staff'
    description: Mapped[Optional[str]] = mapped_column(db.String(255))

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="user_type_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
    )

    def __repr__(self) -> str:
        return f"<UserType id={self.id} code={self.code!r}>"


class UserAffiliation(BaseModel):
    """
    Scopes a user to a company/branch and tags them with a user_type.
    Optional 'linked_entity_*' lets you bind to a concrete domain record
    (e.g., Employees.id, Students.id) without tight FK coupling.

    Examples:
      - user_id=1, company=10, branch=100, user_type='staff',
       linked_entity_id=42
      - user_id=1, company=10, branch=NULL, user_type='guardian',
        linked_entity_id=7
    """
    __tablename__ = "user_affiliations"

    # who
    user_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # scope
    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # classification
    user_type_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("user_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    linked_entity_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True)

    # quality of life
    is_primary: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    # relationships
    user = db.relationship("User", back_populates="affiliations", lazy="joined")
    company = db.relationship("Company", lazy="joined")
    branch = db.relationship("Branch", lazy="joined")
    user_type = db.relationship("UserType", lazy="joined")

    __table_args__ = (
        # prevent duplicate affiliations for the same exact scope + type + entity
        UniqueConstraint(
            "user_id",
            "company_id",
            "branch_id",
            "user_type_id",

            "linked_entity_id",
            name="uq_user_affiliation_scope",
        ),
        Index("ix_user_aff_primary", "user_id", "is_primary"),
        Index("ix_user_aff_entity",  "linked_entity_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<UserAffiliation user_id={self.user_id} company_id={self.company_id} "
            f"branch_id={self.branch_id} user_type_id={self.user_type_id} "
            f"entity={self.linked_entity_kind}:{self.linked_entity_id}>"
        )
