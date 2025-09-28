# app/apps/rbac/models.py
from __future__ import annotations

from typing import Optional
from datetime import datetime
import enum

from sqlalchemy import UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import CITEXT

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


# ---------- Enums ----------
class RoleScopeEnum(str, enum.Enum):
    SYSTEM = "SYSTEM"    # Platform-level role, spans all companies/branches
    COMPANY = "COMPANY"  # Scoped to a company
    BRANCH = "BRANCH"    # Scoped to a branch


# ---------- DocType (single table; ERPNext-style module string + adjacency tree) ----------
class DocType(BaseModel):
    """
    Single-table DocType with module string and simple tree (parent_doctype_id).
    Examples:
      ("Sales", "Sales")            [group]
      ("Sales", "Sales Invoice")    [leaf]
      ("Stock", "Item")             [leaf]
    """
    __tablename__ = "doc_types"
    __table_args__ = (
        # Case-insensitive uniqueness because CITEXT operator class is used
        UniqueConstraint("module", "name", name="uq_doctype_module_name"),
        Index("ix_doctypes_parent", "parent_doctype_id"),
        # Optional: length caps if you care about max sizes (CITEXT behaves like TEXT)
        # CheckConstraint("char_length(module) <= 64",  name="ck_doctype_module_len"),
        # CheckConstraint("char_length(name)   <= 120", name="ck_doctype_name_len"),
        # Safety: disallow self-parent
        CheckConstraint("id <> COALESCE(parent_doctype_id, -1)", name="ck_doctype_no_self_parent"),
    )

    # Core identity (CITEXT = case-insensitive)
    module: Mapped[str] = mapped_column(CITEXT(), nullable=False)  # e.g., "Sales", "Stock"
    name:   Mapped[str] = mapped_column(CITEXT(), nullable=False)  # e.g., "Sales Invoice", "Item"

    description: Mapped[Optional[str]] = mapped_column(db.Text)

    # Tree (adjacency)
    parent_doctype_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("doc_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_group:   Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    tree_depth: Mapped[int]  = mapped_column(db.Integer,  nullable=False, default=0)

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="doctype_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
    )

    # Relationships
    parent = db.relationship(
        "DocType",
        remote_side="DocType.id",
        lazy="joined",
        backref=db.backref("children", lazy="selectin"),
    )
    permissions = db.relationship(
        "Permission",
        back_populates="doctype",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<DocType id={self.id} module={self.module!r} name={self.name!r} depth={self.tree_depth} group={self.is_group}>"


# ---------- Action (dynamic string slugs; no Enum) ----------
class Action(BaseModel):
    """
    Registry of allowed actions (string slug, not Enum).
    Keep uppercase UPPERCASE_SLUG in `name` to avoid duplicates.
    Seed only what you use (e.g., READ, WRITE, CREATE, DELETE, SUBMIT, CANCEL, AMEND, PRINT, EMAIL, EXPORT, IMPORT).
    """
    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("name", name="uq_actions_name"),
        Index("ix_actions_name", "name"),
        Index("ix_actions_is_system_defined", "is_system_defined"),
        Index("ix_actions_is_deprecated", "is_deprecated"),
    )

    # e.g. "READ", "WRITE", "CREATE", ...
    name: Mapped[str] = mapped_column(db.String(32), nullable=False)
    label: Mapped[str] = mapped_column(db.String(64), nullable=False)   # human label (i18n-ready)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    # governance knobs
    is_system_defined: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    is_deprecated:     Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    permissions = db.relationship(
        "Permission",
        back_populates="action",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Action id={self.id} name={self.name!r}>"


# ---------- Permission (DocType × Action) ----------
class Permission(BaseModel):
    """
    A single (DocType, Action) capability.
    Optional company_id lets you maintain per-company grids if you need them; keep NULL for global defaults.
    """
    __tablename__ = "permissions"
    __table_args__ = (
        # Unique across doctype, action, and (optional) company
        UniqueConstraint("doctype_id", "action_id", "company_id", name="uq_permission_doctype_action_company"),
        Index("ix_permissions_doctype_id", "doctype_id"),
        Index("ix_permissions_action_id", "action_id"),
        Index("ix_permissions_company_id", "company_id"),
        Index("ix_permissions_is_system_defined", "is_system_defined"),
    )

    doctype_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("doc_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Optional: per-company permission matrix (NULL = global)
    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    description: Mapped[Optional[str]] = mapped_column(db.Text)
    is_system_defined: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    # Relationships
    doctype = db.relationship("DocType", back_populates="permissions", lazy="joined")
    action  = db.relationship("Action",  back_populates="permissions", lazy="joined")

    role_permissions = db.relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    permission_overrides = db.relationship(
        "PermissionOverride",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Permission id={self.id} doctype_id={self.doctype_id} action_id={self.action_id} company_id={self.company_id}>"


# ---------- Role / RolePermission ----------
class Role(BaseModel):
    """
    Named bundle of permissions. Roles are global by default (SYSTEM scope).
    Companies can define their own roles too (company_id set).
    """
    __tablename__ = "roles"
    __table_args__ = (
        # Role names must be unique within (scope, company_id).
        UniqueConstraint("name", "scope", "company_id", name="uq_role_name_scope_company"),
        Index("ix_roles_name", "name"),
        Index("ix_roles_scope", "scope"),
        Index("ix_roles_company_id", "company_id"),
        Index("ix_roles_is_system_defined", "is_system_defined"),
        Index("ix_roles_status", "status"),
    )

    name: Mapped[str] = mapped_column(db.String(100), nullable=False)
    scope: Mapped[RoleScopeEnum] = mapped_column(
        db.Enum(RoleScopeEnum, name="role_scope_enum"),
        nullable=False,
        default=RoleScopeEnum.SYSTEM,
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )

    is_system_defined: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    status: Mapped[StatusEnum]       = mapped_column(db.Enum(StatusEnum, name="role_status_enum"), nullable=False, default=StatusEnum.ACTIVE)
    description: Mapped[Optional[str]] = mapped_column(db.Text)

    role_permissions = db.relationship("RolePermission", back_populates="role", cascade="all, delete-orphan", lazy="selectin")
    user_roles       = db.relationship("UserRole",       back_populates="role", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r} scope={self.scope} company_id={self.company_id}>"


class RolePermission(BaseModel):
    """
    Many-to-many between Role and Permission. Includes an explicit is_allowed flag
    to support company-specific deny overrides.
    """
    __tablename__ = "role_permissions"
    __table_args__ = (
        # Composite unique constraint for fast lookup of a specific permission
        # for a role within a company context.
        UniqueConstraint("role_id", "permission_id", "company_id", name="uq_role_permission_company"),
        # Indexes for fast lookups. The composite index on role_id and company_id
        # is critical for querying all permissions for a role in a company.
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
        Index("ix_role_permissions_company_id", "company_id"),
        # Combined index for common queries.
        Index("ix_role_permissions_role_company", "role_id", "company_id"),
    )

    role_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # This flag is essential for explicit deny overrides on system-defined roles.
    is_allowed: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    role = db.relationship("Role", back_populates="role_permissions", lazy="joined")
    permission = db.relationship("Permission", back_populates="role_permissions", lazy="joined")

    def __repr__(self) -> str:
        return f"<RolePermission role_id={self.role_id} permission_id={self.permission_id} company_id={self.company_id}>"



# ---------- UserRole (assignment) ----------
class UserRole(BaseModel):
    """
    Assign a Role to a user with an optional scope anchor.
    - SYSTEM roles: company_id/branch_id/user_affiliation_id are NULL.
    - COMPANY roles: company_id and user_affiliation_id point to user's company.
    - BRANCH roles: branch_id (and company via affiliation) point to user's branch.
    Enforce scope compatibility in the service layer.
    """
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "company_id", "branch_id", name="uq_user_role_scope"),
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
        Index("ix_user_roles_company_id", "company_id"),
        Index("ix_user_roles_branch_id", "branch_id"),
        Index("ix_user_roles_user_affiliation_id", "user_affiliation_id"),
        Index("ix_user_roles_is_active", "is_active"),
    )

    user_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Anchor to affiliation for multi-tenant clarity (recommended).
    user_affiliation_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("user_affiliations.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Denormalized anchors for fast filtering & uniqueness.
    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=True,
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger,
        db.ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=True,
    )

    is_active:   Mapped[bool]      = mapped_column(db.Boolean, nullable=False, default=True)
    assigned_by: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at: Mapped[datetime]  = mapped_column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    role = db.relationship("Role", back_populates="user_roles", lazy="joined")
    # (Optional) add backrefs on User/UserAffiliation if you want

    def __repr__(self) -> str:
        return f"<UserRole id={self.id} user_id={self.user_id} role_id={self.role_id} company_id={self.company_id} branch_id={self.branch_id}>"


# ---------- PermissionOverride ----------
class PermissionOverride(BaseModel):
    """
    Per-user allow/deny on a specific Permission (optionally scoped).
    Acts as fine-grained adjustments on top of (Role → Permission).
    """
    __tablename__ = "permission_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_id", "company_id", "branch_id", name="uq_user_permission_override_scope"),
        Index("ix_perm_overrides_user_id", "user_id"),
        Index("ix_perm_overrides_permission_id", "permission_id"),
        Index("ix_perm_overrides_company_id", "company_id"),
        Index("ix_perm_overrides_branch_id", "branch_id"),
        Index("ix_perm_overrides_granted_by", "granted_by"),
    )

    user_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)

    # Scope anchors (optional)
    company_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    branch_id:  Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("branches.id",  ondelete="CASCADE"), nullable=True)

    is_allowed: Mapped[bool] = mapped_column(db.Boolean, nullable=False)  # True=force allow, False=force deny
    reason:     Mapped[Optional[str]] = mapped_column(db.Text)

    granted_by: Mapped[Optional[int]] = mapped_column(db.BigInteger, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    permission = db.relationship("Permission", back_populates="permission_overrides", lazy="joined")

    def __repr__(self) -> str:
        return f"<PermissionOverride user_id={self.user_id} permission_id={self.permission_id} allow={self.is_allowed}>"


# ---------- UserConstraint (Frappe-style "User Permission") ----------
class UserConstraint(BaseModel):
    """
    Limit a user's scope for linked fields. Example:
      - doctype="Stock Entry", field="target_warehouse", ref_doctype="Warehouse", ref_id=<warehouse_id>
    The permission engine should enforce/merge these while querying/validating.
    """
    __tablename__ = "user_constraints"
    __table_args__ = (
        UniqueConstraint("user_id", "doctype_id", "field_name", "ref_doctype_id", "ref_id", name="uq_user_constraint"),
        Index("ix_user_constraints_user_id", "user_id"),
        Index("ix_user_constraints_doctype_id", "doctype_id"),
        Index("ix_user_constraints_field_name", "field_name"),
        Index("ix_user_constraints_ref_doctype_id", "ref_doctype_id"),
        Index("ix_user_constraints_ref_id", "ref_id"),
    )

    user_id: Mapped[int] = mapped_column(db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    doctype_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("doc_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(db.String(100), nullable=False)  # e.g., "warehouse", "item_group"

    ref_doctype_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("doc_types.id", ondelete="CASCADE"),  # referenced doctype (e.g., Warehouse)
        nullable=False,
    )
    ref_id: Mapped[int] = mapped_column(db.BigInteger, nullable=False)  # the allowed record's PK in ref_doctype

    allow_children: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)  # for tree doctypes

    def __repr__(self) -> str:
        return f"<UserConstraint user_id={self.user_id} doctype_id={self.doctype_id} field={self.field_name} ref_id={self.ref_id}>"
