# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from config.database import db
from app.common.models.base import BaseModel


class ModulePackage(BaseModel):
    """
    Sellable bundle: 'education', 'inventory', 'full_suite', etc.
    """
    __tablename__ = "module_packages"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_module_package_slug"),
        Index("ix_module_package_is_enabled", "is_enabled"),
    )

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    slug: Mapped[str] = mapped_column(db.String(50),  nullable=False)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=db.text("'{}'::jsonb"))

    package_workspaces: Mapped[List["PackageWorkspace"]] = relationship(
        back_populates="package", cascade="all, delete-orphan"
    )


class PackageWorkspace(BaseModel):
    """
    Which workspaces are included in a package.
    """
    __tablename__ = "package_workspaces"
    __table_args__ = (
        UniqueConstraint("package_id", "workspace_id", name="uq_package_workspace"),
        Index("ix_pkgws_package", "package_id"),
        Index("ix_pkgws_workspace", "workspace_id"),
    )

    package_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("module_packages.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    package: Mapped["ModulePackage"] = relationship(back_populates="package_workspaces")


class CompanyPackageSubscription(BaseModel):
    """
    Company subscribes to packages (SaaS layer).
    """
    __tablename__ = "company_package_subscriptions"
    __table_args__ = (
        UniqueConstraint("company_id", "package_id", name="uq_company_package"),
        Index("ix_cps_company", "company_id"),
        Index("ix_cps_package", "package_id"),
        Index("ix_cps_is_enabled", "is_enabled"),
    )

    company_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    package_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("module_packages.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    is_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True, index=True)
    valid_from: Mapped[db.DateTime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    valid_until: Mapped[Optional[db.DateTime]] = mapped_column(db.DateTime(timezone=True), nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=db.text("'{}'::jsonb"))
