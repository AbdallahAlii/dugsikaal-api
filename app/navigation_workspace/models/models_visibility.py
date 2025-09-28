# app/navigation_workspace/models/models_visibility.py
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Index, CheckConstraint, text
from config.database import db
from app.common.models.base import BaseModel


class SystemNavVisibility(BaseModel):
    """
    System Owner rule: per-company visibility gate for either:
      - a whole workspace (module), or
      - a single link inside a workspace.

    Scope: company ONLY (no branch / user here).
    Tri-state not needed; we store explicit is_enabled True/False.
    """
    __tablename__ = "system_nav_visibility"
    __table_args__ = (
        # Exactly one target must be set (XOR)
        CheckConstraint(
            "((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))",
            name="ck_sysvis_xor_target"
        ),
        # Partial uniques to prevent duplicates per company/target
        Index(
            "uq_sysvis_company_workspace",
            "company_id", "workspace_id",
            unique=True,
            postgresql_where=text("link_id IS NULL")
        ),
        Index(
            "uq_sysvis_company_link",
            "company_id", "link_id",
            unique=True,
            postgresql_where=text("workspace_id IS NULL")
        ),
        Index("ix_sysvis_company", "company_id"),
    )

    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    workspace_id: Mapped[Optional[int]] = mapped_column(db.BigInteger,
                                                        db.ForeignKey("workspaces.id", ondelete="CASCADE"),
                                                        nullable=True, index=True)
    link_id: Mapped[Optional[int]] = mapped_column(db.BigInteger,
                                                   db.ForeignKey("workspace_links.id", ondelete="CASCADE"),
                                                   nullable=True, index=True)

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    reason: Mapped[Optional[str]] = mapped_column(db.String(255))


class CompanyNavVisibility(BaseModel):
    """
    Company Admin rule: can target entire company, a branch, or a single user.
    Target can be a workspace OR a link (XOR).
    Tri-state via inheritance is handled by resolver (missing row = inherit).
    """
    __tablename__ = "company_nav_visibility"
    __table_args__ = (
        # Exactly one target must be set (XOR)
        CheckConstraint(
            "((workspace_id IS NOT NULL) <> (link_id IS NOT NULL))",
            name="ck_cmpvis_xor_target"
        ),
        # company required
        CheckConstraint("company_id IS NOT NULL", name="ck_cmpvis_company_required"),
        # Partial uniques to prevent duplicates at each scope level
        Index(
            "uq_cmpvis_co_workspace",
            "company_id", "workspace_id",
            unique=True,
            postgresql_where=text("link_id IS NULL AND branch_id IS NULL AND user_id IS NULL")
        ),
        Index(
            "uq_cmpvis_branch_workspace",
            "company_id", "branch_id", "workspace_id",
            unique=True,
            postgresql_where=text("link_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL")
        ),
        Index(
            "uq_cmpvis_user_workspace",
            "company_id", "user_id", "workspace_id",
            unique=True,
            postgresql_where=text("link_id IS NULL AND user_id IS NOT NULL")
        ),
        Index(
            "uq_cmpvis_co_link",
            "company_id", "link_id",
            unique=True,
            postgresql_where=text("workspace_id IS NULL AND branch_id IS NULL AND user_id IS NULL")
        ),
        Index(
            "uq_cmpvis_branch_link",
            "company_id", "branch_id", "link_id",
            unique=True,
            postgresql_where=text("workspace_id IS NULL AND branch_id IS NOT NULL AND user_id IS NULL")
        ),
        Index(
            "uq_cmpvis_user_link",
            "company_id", "user_id", "link_id",
            unique=True,
            postgresql_where=text("workspace_id IS NULL AND user_id IS NOT NULL")
        ),
        Index("ix_cmpvis_company", "company_id"),
        Index("ix_cmpvis_branch", "branch_id"),
        Index("ix_cmpvis_user", "user_id"),
    )

    # Scope
    company_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"),
                                            nullable=False, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id", ondelete="CASCADE"),
                                                     nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"),
                                                   nullable=True, index=True)

    # Target (XOR)
    workspace_id: Mapped[Optional[int]] = mapped_column(db.BigInteger,
                                                        db.ForeignKey("workspaces.id", ondelete="CASCADE"),
                                                        nullable=True, index=True)
    link_id: Mapped[Optional[int]] = mapped_column(db.BigInteger,
                                                   db.ForeignKey("workspace_links.id", ondelete="CASCADE"),
                                                   nullable=True, index=True)

    # Decision
    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)