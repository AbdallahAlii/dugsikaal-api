from __future__ import annotations
from typing import Optional, List

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from config.database import db
from app.common.models.base import BaseModel  # your base with id, created_at, etc.


class Doctype(BaseModel):
    __tablename__ = "doctypes"

    # e.g. "Company", "Branch", "Department"
    name: Mapped[str] = mapped_column(db.String(140), unique=True, nullable=False, index=True)

    # Display label, like "Company"
    label: Mapped[str] = mapped_column(db.String(140), nullable=False)

    # Logical module/group, e.g. "Organization", "Accounts", "HR"
    module: Mapped[str] = mapped_column(db.String(140), nullable=False, index=True)

    # Underlying table name in Postgres, e.g. "companies", "branches"
    table_name: Mapped[str] = mapped_column(db.String(140), nullable=False)

    # Optional icon name (lucide or fontawesome)
    icon: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True)

    is_child: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    is_single: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    is_tree: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    is_submittable: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    track_changes: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    track_seen: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    track_views: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)

    quick_entry: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    description: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    # Relationships
    fields: Mapped[List["DocField"]] = db.relationship(
        "DocField",
        back_populates="doctype",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DocField.idx",
    )


    list_views: Mapped[List["DocListView"]] = db.relationship(
        "DocListView",
        back_populates="doctype",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Doctype id={self.id} name={self.name!r}>"


class DocField(BaseModel):
    __tablename__ = "docfields"

    doctype_id: Mapped[int] = mapped_column(
        db.BigInteger,
        ForeignKey("doctypes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # database column name or virtual name
    fieldname: Mapped[str] = mapped_column(db.String(140), nullable=False)

    # label shown on UI
    label: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True)

    # "Data", "Int", "Link", "Select", "Date", "Section Break", "Column Break", etc.
    fieldtype: Mapped[str] = mapped_column(db.String(50), nullable=False)

    # For Link: target Doctype name ("City", "Company"...)
    # For Select: newline-separated choices
    options: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)

    default: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    reqd: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    read_only: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    hidden: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    in_list_view: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    in_filter: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    in_quick_entry: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)

    idx: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)

    description: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    # Optional tenant-specific field: per company, etc.
    company_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)

    doctype: Mapped["Doctype"] = db.relationship("Doctype", back_populates="fields")

    def __repr__(self) -> str:
        return f"<DocField id={self.id} doctype_id={self.doctype_id} fieldname={self.fieldname!r}>"



class DocListView(BaseModel):
    __tablename__ = "doclist_views"

    doctype_id: Mapped[int] = mapped_column(
        db.BigInteger,
        ForeignKey("doctypes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # null = default for everyone
    user_id: Mapped[Optional[int]] = mapped_column(db.BigInteger, nullable=True, index=True)

    # or use per-role list view
    role_name: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True, index=True)

    # store columns & filters in JSON (for now simple text, can change to JSONB if you want)
    columns_json: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    filters_json: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    sort_by: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True)
    sort_order: Mapped[Optional[str]] = mapped_column(db.String(4), nullable=True)  # "asc"/"desc"

    doctype: Mapped["Doctype"] = db.relationship("Doctype", back_populates="list_views")


class DocLink(BaseModel):
    __tablename__ = "doclinks"

    # 👉 your question: why names not ids?
    # We'll discuss below. For now, use names like Frappe.
    parent_doctype: Mapped[str] = mapped_column(db.String(140), nullable=False, index=True)
    link_doctype: Mapped[str] = mapped_column(db.String(140), nullable=False, index=True)

    # child field that references parent (e.g. "company_id")
    link_fieldname: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True)

    group_label: Mapped[Optional[str]] = mapped_column(db.String(140), nullable=True)
