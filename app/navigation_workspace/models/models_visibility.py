
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UniqueConstraint, Index
from config.database import db
from app.common.models.base import BaseModel


class SystemWorkspaceVisibility(BaseModel):
    """
    Platform owner control per company × workspace.
    Missing row => inherit.
    """
    __tablename__ = "system_workspace_visibility"
    __table_args__ = (
        UniqueConstraint("company_id", "workspace_id", name="uq_sys_vis_company_workspace"),
        Index("ix_sysvis_company", "company_id"),
        Index("ix_sysvis_workspace", "workspace_id"),
    )

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(db.String(255))


class CompanyWorkspaceVisibility(BaseModel):
    """
    Tenant admin overrides: company-wide, per-branch, or per-user.
    Precedence: user > branch > company > system > implicit.
    """
    __tablename__ = "company_workspace_visibility"
    __table_args__ = (
        UniqueConstraint("company_id", "workspace_id", "branch_id", "user_id",
                         name="uq_cmp_vis_company_workspace_branch_user"),
        Index("ix_cmpvis_company", "company_id"),
        Index("ix_cmpvis_workspace", "workspace_id"),
        Index("ix_cmpvis_branch", "branch_id"),
        Index("ix_cmpvis_user", "user_id"),
    )

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True
    )

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(db.String(255))
