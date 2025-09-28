# app/navigation_workspace/models/navigation_workspace.py
from __future__ import annotations
import enum
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    UniqueConstraint, Index, CheckConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB
from config.database import db
from app.common.models.base import BaseModel, StatusEnum

class NavLinkTypeEnum(str, enum.Enum):
    LIST = "LIST"
    FORM_NEW = "FORM_NEW"
    REPORT = "REPORT"
    PAGE = "PAGE"
    EXTERNAL = "EXTERNAL"

class Workspace(BaseModel):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspace_slug"),
        Index("ix_ws_status", "status"),
        Index("ix_ws_order", "order_index"),
        Index("ix_ws_admin_only", "admin_only"),
    )
    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    slug:  Mapped[str] = mapped_column(db.String(64),  nullable=False)
    icon:  Mapped[Optional[str]] = mapped_column(db.String(64))
    description: Mapped[Optional[str]] = mapped_column(db.String(255))
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)
    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="statusenum"),  # ⬅️ explicit, reuse existing DB type
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )
    # 🔹 NEW: mark workspaces that should only be visible to System Admin
    admin_only: Mapped[bool] = mapped_column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    feature_flag: Mapped[Optional[str]] = mapped_column(db.String(64), index=True)
    domain_key:   Mapped[Optional[str]] = mapped_column(db.String(64), index=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    sections: Mapped[List["WorkspaceSection"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", order_by="WorkspaceSection.order_index"
    )
    root_links: Mapped[List["WorkspaceLink"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan",
        primaryjoin="Workspace.id==WorkspaceLink.workspace_id",
        order_by="WorkspaceLink.order_index"
    )

class WorkspaceSection(BaseModel):
    __tablename__ = "workspace_sections"
    __table_args__ = (Index("ix_ws_section_ws", "workspace_id"),)
    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(db.String(120), nullable=False)
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    workspace: Mapped["Workspace"] = relationship(back_populates="sections")
    links: Mapped[List["WorkspaceLink"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="WorkspaceLink.order_index"
    )

class WorkspaceLink(BaseModel):
    __tablename__ = "workspace_links"
    __table_args__ = (
        Index("ix_wslink_section", "section_id"),
        Index("ix_wslink_workspace", "workspace_id"),
        Index("ix_wslink_type", "link_type"),
        # 🔽 permission lookup hot-paths:
        Index("ix_wslink_doctype", "doctype_id"),
        Index("ix_wslink_action", "required_action_id"),
        Index("ix_wslink_dt_act", "doctype_id", "required_action_id"),
        CheckConstraint(
            "((workspace_id IS NOT NULL) <> (section_id IS NOT NULL))",
            name="ck_wslink_xor_anchor"
        ),
        CheckConstraint(
            "(link_type <> 'EXTERNAL' AND route_path NOT LIKE 'http%') "
            "OR (link_type = 'EXTERNAL' AND route_path LIKE 'http%')",
            name="ck_wslink_route_matches_type"
        ),
        CheckConstraint(
            "("
            "(doctype_id IS NOT NULL AND required_action_id IS NOT NULL) "
            "OR (required_permission_str IS NOT NULL) "
            "OR (doctype_id IS NULL AND required_action_id IS NULL AND required_permission_str IS NULL)"
            ")",
            name="ck_wslink_perm_binding"
        ),
    )

    workspace_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    section_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("workspace_sections.id", ondelete="CASCADE"), nullable=True
    )

    label: Mapped[str] = mapped_column(db.String(160), nullable=False)
    link_type: Mapped[NavLinkTypeEnum] = mapped_column(
        db.Enum(NavLinkTypeEnum, name="navlinktypeenum"),
        nullable=False
    )

    route_path: Mapped[str] = mapped_column(db.String(255), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(db.String(64))
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)

    doctype_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("doc_types.id"), nullable=True, index=True)
    required_action_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("actions.id"), nullable=True, index=True)
    required_permission_str: Mapped[Optional[str]] = mapped_column(db.String(180), nullable=True, index=True)

    keywords: Mapped[Optional[str]] = mapped_column(db.String(255))
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    workspace: Mapped[Optional["Workspace"]] = relationship(back_populates="root_links")
    section:   Mapped[Optional["WorkspaceSection"]] = relationship(back_populates="links")
