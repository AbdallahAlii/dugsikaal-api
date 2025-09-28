# app/models/base.py
from __future__ import annotations
from datetime import datetime, date, time, timezone
from typing import Any, Iterable, Mapping, Optional
import enum
import uuid

from sqlalchemy import func, select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column
from config.database import db


# ---------- Mixins ----------

class PKMixin:
    """Primary key column (BIGINT)."""
    id: Mapped[int] = mapped_column(db.BigInteger, primary_key=True)


class TimestampMixin:
    """Created/Updated timestamps (timezone-aware; DB-maintained)."""
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """Soft-delete flags."""
    is_deleted: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime(timezone=True), nullable=True)

    def soft_delete(self) -> None:
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)  # timezone-aware


# Example status enum you can reuse
class StatusEnum(str, enum.Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"

class GenderEnum(str, enum.Enum):
    MALE = "Male"
    FEMALE = "Female"

class PersonRelationshipEnum(str, enum.Enum):
    FATHER = "Father"
    MOTHER = "Mother"
    GUARDIAN = "Guardian"
    CHILD = "Child"
    OTHER = "Other"


# ---------- BaseModel ----------
class BaseModel(db.Model, PKMixin, TimestampMixin):
    """
    Common base for all models.
    - Typed columns (SQLA 2.x Mapped).
    - Safe to_dict() with optional relationship traversal.
    - Pagination via select() + db.paginate() (Flask-SQLAlchemy v3 style).
    """
    __abstract__ = True

    # ---- Serialization ----
    def to_dict(
        self,
        *,
        include: Optional[Iterable[str]] = None,
        exclude: Optional[Iterable[str]] = None,
        include_relationships: bool = False,
        max_depth: int = 1,
    ) -> dict[str, Any]:
        inc = set(include or [])
        excl = set(exclude or [])

        mapper = sa_inspect(self.__class__)
        data: dict[str, Any] = {}

        # columns
        for col in mapper.columns:
            name = col.key
            if inc and name not in inc:
                continue
            if name in excl:
                continue
            data[name] = _serialize_value(getattr(self, name))

        # relationships (opt-in; shallow by default)
        if include_relationships and max_depth > 0:
            for rel in mapper.relationships:
                key = rel.key
                if inc and key not in inc:
                    continue
                if key in excl:
                    continue
                attr = getattr(self, key)
                if attr is None:
                    data[key] = None
                elif rel.uselist:
                    data[key] = [
                        (
                            obj.to_dict(
                                include=None,
                                exclude=excl,
                                include_relationships=False if max_depth == 1 else True,
                                max_depth=max_depth - 1,
                            )
                            if hasattr(obj, "to_dict")
                            else _serialize_value(obj)
                        )
                        for obj in list(attr)
                    ]
                else:
                    data[key] = (
                        attr.to_dict(
                            include=None,
                            exclude=excl,
                            include_relationships=False if max_depth == 1 else True,
                            max_depth=max_depth - 1,
                        )
                        if hasattr(attr, "to_dict")
                        else _serialize_value(attr)
                    )

        return data

    # alias
    as_dict = to_dict

    # ---- Query helpers (SQLA 2.x / FSA 3.x) ----
    @classmethod
    def paginate(
        cls,
        *,
        page: int = 1,
        per_page: int = 20,
        filters: Optional[Mapping[str, Any]] = None,
        order_by: Optional[str] = None,
        only_not_deleted: bool = True,
    ):
        """
        Build a SELECT and use db.paginate() (Flask-SQLAlchemy v3).
        Supports simple filter_by() semantics and order string like "-created_at".
        """
        stmt = select(cls)

        # soft-delete filter if model has is_deleted
        if only_not_deleted and hasattr(cls, "is_deleted"):
            stmt = stmt.where(getattr(cls, "is_deleted").is_(False))

        # filters via equality
        if filters:
            for k, v in filters.items():
                if hasattr(cls, k):
                    stmt = stmt.where(getattr(cls, k) == v)

        # order_by by name; prefix '-' for desc
        if order_by:
            desc = order_by.startswith("-")
            field = order_by[1:] if desc else order_by
            if hasattr(cls, field):
                col = getattr(cls, field)
                stmt = stmt.order_by(col.desc() if desc else col.asc())

        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @classmethod
    def get(cls, pk: Any) -> Optional["BaseModel"]:
        return db.session.get(cls, pk)

    def __repr__(self) -> str:
        mapper = sa_inspect(self.__class__)
        parts: list[str] = []
        for col in mapper.columns:
            key = col.key
            if key in {"created_at", "updated_at"}:
                continue
            try:
                parts.append(f"{key}={getattr(self, key)!r}")
            except Exception:
                pass
        return f"<{self.__class__.__name__} {' '.join(parts)}>"


# ---------- Serialization util ----------
def _serialize_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, uuid.UUID):
        return str(v)
    return repr(v)
