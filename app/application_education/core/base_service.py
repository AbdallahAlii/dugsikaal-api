from __future__ import annotations

import logging
from typing import Type, TypeVar, Generic, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session

from config.database import db
from app.business_validation.item_validation import BizValidationError

T = TypeVar("T")
log = logging.getLogger(__name__)


class BaseEducationService(Generic[T]):
    """
    Document-like lifecycle hooks (Frappe style):
      - validate_create / validate_update
      - before_save / after_save
      - before_delete / after_delete

    Important:
      - No RBAC here.
      - Nested transaction safe (commit-or-flush like your EducationService).
    """

    def __init__(self, model_class: Type[T], session: Optional[Session] = None):
        self.model_class = model_class
        self.s: Session = session or db.session

    # ---------- Tx helpers ----------

    @property
    def _in_nested_tx(self) -> bool:
        try:
            fn = getattr(self.s, "in_nested_transaction", None)
            if callable(fn):
                return bool(fn())
        except Exception:
            pass

        tx = getattr(self.s, "transaction", None)
        if tx is None:
            return False
        if getattr(tx, "nested", False):
            return True

        parent = getattr(tx, "parent", None)
        while parent is not None:
            if getattr(parent, "nested", False):
                return True
            parent = parent.parent
        return False

    def _commit_or_flush(self) -> None:
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        if self._in_nested_tx:
            return
        self.s.rollback()

    # ---------- Hooks (override in domain service if needed) ----------

    def validate_create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return data

    def validate_update(self, obj: T, data: Dict[str, Any]) -> Dict[str, Any]:
        return data

    def before_save(self, obj: T, *, is_new: bool) -> None:
        return

    def after_save(self, obj: T, *, is_new: bool) -> None:
        return

    def before_delete(self, obj: T) -> None:
        return

    def after_delete(self, obj: T) -> None:
        return

    # ---------- Generic CRUD ----------

    def create_doc(self, data: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            data = self.validate_create(data)
            obj = self.model_class(**data)

            self.before_save(obj, is_new=True)

            self.s.add(obj)
            self.s.flush([obj])

            self.after_save(obj, is_new=True)
            self._commit_or_flush()

            return True, f"{self.model_class.__name__} created", {
                "id": getattr(obj, "id", None),
                "name": getattr(obj, "name", None),
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("create_doc failed: %s", e)
            return False, "Unexpected error.", None

    def update_doc(self, obj: T, data: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            data = self.validate_update(obj, data)

            for k, v in data.items():
                if hasattr(obj, k) and v is not None:
                    setattr(obj, k, v)

            self.before_save(obj, is_new=False)

            self.s.flush([obj])

            self.after_save(obj, is_new=False)
            self._commit_or_flush()

            return True, f"{self.model_class.__name__} updated", {
                "id": getattr(obj, "id", None),
                "name": getattr(obj, "name", None),
            }

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            self._rollback_if_top_level()
            log.exception("update_doc failed: %s", e)
            return False, "Unexpected error.", None

    def delete_doc(self, obj: T, *, soft: bool = True) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            self.before_delete(obj)

            if soft and hasattr(obj, "is_enabled"):
                setattr(obj, "is_enabled", False)
                self.s.flush([obj])
            else:
                self.s.delete(obj)
                self.s.flush()

            self.after_delete(obj)
            self._commit_or_flush()

            return True, f"{self.model_class.__name__} deleted", {"id": getattr(obj, "id", None)}

        except Exception as e:
            self._rollback_if_top_level()
            log.exception("delete_doc failed: %s", e)
            return False, "Unexpected error.", None
