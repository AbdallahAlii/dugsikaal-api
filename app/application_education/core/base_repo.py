from __future__ import annotations

from typing import Type, TypeVar, Generic, Optional, List, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.database import db

T = TypeVar("T")


class BaseEducationRepo(Generic[T]):
    """
    Generic repo for SQLAlchemy models.
    Keep it simple. Domain repos extend for special queries.
    """

    def __init__(self, model_class: Type[T], session: Optional[Session] = None):
        self.model_class = model_class
        self.s: Session = session or db.session

    def get(self, id: int) -> Optional[T]:
        return self.s.get(self.model_class, id)

    def get_by(self, **filters) -> Optional[T]:
        stmt = select(self.model_class).filter_by(**filters)
        return self.s.scalar(stmt)

    def list(self, **filters) -> List[T]:
        stmt = select(self.model_class)
        if filters:
            stmt = stmt.filter_by(**filters)
        return list(self.s.scalars(stmt.order_by(getattr(self.model_class, "id"))))

    def exists(self, **filters) -> bool:
        stmt = select(getattr(self.model_class, "id")).filter_by(**filters).limit(1)
        return self.s.scalar(stmt) is not None

    def count(self, **filters) -> int:
        stmt = select(func.count()).select_from(self.model_class)
        if filters:
            stmt = stmt.filter_by(**filters)
        return int(self.s.scalar(stmt) or 0)

    def create(self, data: Dict[str, Any]) -> T:
        obj = self.model_class(**data)
        self.s.add(obj)
        self.s.flush([obj])
        return obj

    def update_fields(self, obj: T, data: Dict[str, Any]) -> T:
        for k, v in data.items():
            if hasattr(obj, k) and v is not None:
                setattr(obj, k, v)
        self.s.flush([obj])
        return obj

    def delete(self, obj: T) -> None:
        self.s.delete(obj)
        self.s.flush()

    def soft_delete(self, obj: T) -> None:
        # ERP behavior: disable if possible
        if hasattr(obj, "is_enabled"):
            setattr(obj, "is_enabled", False)
            self.s.flush([obj])
        else:
            self.delete(obj)
