# # app/navigation_workspace/models/navigation_workspace.py

from __future__ import annotations
import enum
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from config.database import db
from app.common.models.base import BaseModel


class PageKindEnum(str, enum.Enum):
    """Frappe-ish desk page kinds (only for non-standard 'Page' routes)."""
    PAGE = "PAGE"
    DASHBOARD = "DASHBOARD"
    SETTINGS = "SETTINGS"


class Workspace(BaseModel):
    """
    Frappe-style Workspace (module). We sell/enable these via packages.
    """
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspace_slug"),
        Index("ix_ws_order", "order_index"),
        Index("ix_ws_admin_only", "is_system_only"),
        Index("ix_ws_is_enabled", "is_enabled"),
    )

    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    slug:  Mapped[str] = mapped_column(db.String(64),  nullable=False)  # 'selling', 'education', 'hr', ...
    icon:  Mapped[Optional[str]] = mapped_column(db.String(64))
    description: Mapped[Optional[str]] = mapped_column(db.String(255))

    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)

    # Frappe often uses "disabled"; we use the positive toggle "is_enabled".
    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    # Hide from everyone unless platform admin
    is_system_only: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Optional metadata
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    # Relationships
    sections: Mapped[List["WorkspaceSection"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan",
        order_by="WorkspaceSection.order_index"
    )
    pages: Mapped[List["Page"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan",
        order_by="Page.order_index"
    )


class WorkspaceSection(BaseModel):
    """
    Logical grouping inside a Workspace (e.g., "Student Enrollment", "Billing").
    """
    __tablename__ = "workspace_sections"
    __table_args__ = (
        Index("ix_wssection_workspace", "workspace_id"),
        Index("ix_wssection_order", "order_index"),
    )

    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(db.String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.String(255))
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    workspace: Mapped["Workspace"] = relationship(back_populates="sections")
    page_links: Mapped[List["WorkspacePageLink"]] = relationship(
        back_populates="section", cascade="all, delete-orphan",
        order_by="WorkspacePageLink.order_index"
    )


class Page(BaseModel):
    """
    Registry for *non-standard* desk routes (custom pages/dashboards/settings).
    Standard routes (List/Form/Report) are resolved by pattern; see resolver.
    """
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("route_path", name="uq_page_route"),
        UniqueConstraint("slug", name="uq_page_slug"),
        Index("ix_page_workspace", "workspace_id"),
        Index("ix_page_kind", "kind"),
        Index("ix_page_doctype", "doctype_id"),
        Index("ix_page_is_enabled", "is_enabled"),
    )

    # Identity
    title: Mapped[str] = mapped_column(db.String(160), nullable=False)
    slug:  Mapped[str] = mapped_column(db.String(120), nullable=False)  # 'accounting-settings', 'edu-dashboard'
    kind:  Mapped[PageKindEnum] = mapped_column(db.Enum(PageKindEnum, name="page_kind_enum"), nullable=False)

    # Route like '/app/page/accounting-settings'
    route_path: Mapped[str] = mapped_column(db.String(255), nullable=False)

    # Ownership
    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Optional DocType/Action guard (rare for custom pages)
    doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("doc_types.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    default_action_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("actions.id", ondelete="SET NULL"),
        nullable=True, index=True
    )

    icon: Mapped[Optional[str]] = mapped_column(db.String(64))
    description: Mapped[Optional[str]] = mapped_column(db.String(255))
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)

    # Enabled toggle for the page itself
    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)

    keywords: Mapped[Optional[str]] = mapped_column(db.String(255))
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    workspace: Mapped["Workspace"] = relationship(back_populates="pages")


class WorkspacePageLink(BaseModel):
    """
    UI shortcuts under sections pointing to a Page (custom) or to a standard route via 'target_route'.
    """
    __tablename__ = "workspace_page_links"
    __table_args__ = (
        UniqueConstraint("section_id", "page_id", "target_route", name="uq_ws_page_link"),
        Index("ix_wslink_section", "section_id"),
        Index("ix_wslink_page", "page_id"),
        Index("ix_wslink_order", "order_index"),
    # exactly one of (page_id, target_route) must be set
        CheckConstraint(
            "((page_id IS NOT NULL) <> (target_route IS NOT NULL))",
            name="ck_wslink_xor_page_vs_route"
        )
    )

    section_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspace_sections.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    # EITHER link a custom Page...
    page_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("pages.id", ondelete="CASCADE"),
        nullable=True, index=True
    )
    # ...OR link a standard desk route (List/Form/Report) directly
    target_route: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)

    label: Mapped[Optional[str]] = mapped_column(db.String(160))
    order_index: Mapped[int] = mapped_column(db.Integer, nullable=False, default=100)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    section: Mapped["WorkspaceSection"] = relationship(back_populates="page_links")
    page:    Mapped[Optional["Page"]] = relationship()


