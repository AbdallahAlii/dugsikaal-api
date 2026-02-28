from __future__ import annotations

from typing import Any, Dict, Generic, List, Optional, Sequence, Type, TypeVar

from sqlalchemy import delete, update
from sqlalchemy.orm import Session, selectinload

from config.database import db

T = TypeVar("T")


class BaseEducationRepo(Generic[T]):
    """
    Write-focused repo (Create/Update/Delete) for EDU modules.

    Design goals:
      - Very low overhead
      - Bulk operations use single SQL queries (no N+1)
      - Optional scope filters: company_id + branch_id when model supports them
      - Eager loading helper included for your read-layer/domain repos
    """

    def __init__(self, model: Type[T], session: Optional[Session] = None):
        self.model = model
        self.s: Session = session or db.session

    # ---------- capability checks ----------

    def _tenant_aware(self) -> bool:
        return hasattr(self.model, "company_id")

    def _branch_aware(self) -> bool:
        return hasattr(self.model, "branch_id")

    def _has_enabled(self) -> bool:
        return hasattr(self.model, "is_enabled")

    # ---------- stmt helpers (for bulk ops / read-layer use) ----------

    def apply_scope(self, stmt, *, company_id: Optional[int] = None, branch_id: Optional[int] = None):
        if company_id is not None and self._tenant_aware():
            stmt = stmt.where(getattr(self.model, "company_id") == int(company_id))
        if branch_id is not None and self._branch_aware():
            stmt = stmt.where(getattr(self.model, "branch_id") == int(branch_id))
        return stmt

    def apply_eager(self, stmt, eager_load: Optional[Sequence[str]] = None):
        """
        Helper for your read layer/domain repos:
        pass relationship names to avoid N+1 (selectinload).
        """
        if eager_load:
            for rel in eager_load:
                if hasattr(self.model, rel):
                    stmt = stmt.options(selectinload(getattr(self.model, rel)))
        return stmt

    # ---------- create ----------

    def create(self, data: Dict[str, Any]) -> T:
        obj = self.model(**data)
        self.s.add(obj)
        self.s.flush([obj])
        return obj

    def create_many(self, items: List[Dict[str, Any]]) -> List[T]:
        """
        Bulk insert (fast):
          - Creates objects in memory
          - add_all + single flush
        """
        if not items:
            return []
        objs = [self.model(**d) for d in items]
        self.s.add_all(objs)
        self.s.flush()
        return objs

    # ---------- update (bulk) ----------

    def update_many(
        self,
        ids: List[int],
        data: Dict[str, Any],
        *,
        company_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> int:
        """
        Bulk update using a single UPDATE query.
        """
        ids = [int(x) for x in (ids or []) if x]
        if not ids or not data:
            return 0

        stmt = update(self.model).where(getattr(self.model, "id").in_(ids))
        stmt = self.apply_scope(stmt, company_id=company_id, branch_id=branch_id)
        stmt = stmt.values(**data).execution_options(synchronize_session="fetch")

        res = self.s.execute(stmt)
        self.s.flush()
        return int(res.rowcount or 0)

    # ---------- delete (single object) ----------

    def hard_delete_obj(self, obj: T) -> None:
        self.s.delete(obj)
        self.s.flush()

    def soft_delete_obj(self, obj: T) -> None:
        if self._has_enabled():
            setattr(obj, "is_enabled", False)
            self.s.flush([obj])
        else:
            self.hard_delete_obj(obj)

    # ---------- delete (bulk) ----------

    def hard_delete_many(
        self,
        ids: List[int],
        *,
        company_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> int:
        """
        Bulk hard delete via single DELETE query.
        """
        ids = [int(x) for x in (ids or []) if x]
        if not ids:
            return 0

        stmt = delete(self.model).where(getattr(self.model, "id").in_(ids))
        stmt = self.apply_scope(stmt, company_id=company_id, branch_id=branch_id)
        stmt = stmt.execution_options(synchronize_session="fetch")

        res = self.s.execute(stmt)
        self.s.flush()
        return int(res.rowcount or 0)

    def soft_delete_many(
        self,
        ids: List[int],
        *,
        company_id: Optional[int] = None,
        branch_id: Optional[int] = None,
    ) -> int:
        """
        Bulk soft delete:
          - if model has is_enabled: single UPDATE is_enabled=false
          - otherwise: falls back to hard delete
        """
        ids = [int(x) for x in (ids or []) if x]
        if not ids:
            return 0

        if not self._has_enabled():
            return self.hard_delete_many(ids, company_id=company_id, branch_id=branch_id)

        stmt = update(self.model).where(getattr(self.model, "id").in_(ids))
        stmt = self.apply_scope(stmt, company_id=company_id, branch_id=branch_id)
        stmt = stmt.values(is_enabled=False).execution_options(synchronize_session="fetch")

        res = self.s.execute(stmt)
        self.s.flush()
        return int(res.rowcount or 0)