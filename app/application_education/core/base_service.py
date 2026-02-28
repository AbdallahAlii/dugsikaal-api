from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Generic, Iterable, List, Optional, Sequence, Tuple, Type, TypeVar, Literal

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import db
from app.business_validation.item_validation import BizValidationError
from app.application_education.core.base_repo import BaseEducationRepo  # adjust import path to your project

log = logging.getLogger(__name__)
T = TypeVar("T")
TxMode = Literal["service", "external"]  # service commits; external only flushes


class _UnsetType:
    pass


UNSET = _UnsetType()


def _format_date_out(v: Any) -> Any:
    if isinstance(v, datetime):
        # keep only date portion; you can keep time if you want
        return v.strftime("%d-%m-%Y")
    if isinstance(v, date):
        return v.strftime("%d-%m-%Y")
    return v


def _safe_scalar_attr(obj: Any, key: str) -> Any:
    """
    Avoid triggering lazy-load after commit / expired state.
    Reads only if attribute isn't expired.
    """
    try:
        state = sa_inspect(obj)
        if key in getattr(state, "expired_attributes", set()):
            return None
    except Exception:
        pass
    try:
        return getattr(obj, key)
    except Exception:
        return None


def _pick(d: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        if k in d:
            out[k] = d[k]
    return out


class BaseEducationService(Generic[T]):
    """
    Frappe-like document service:
      - validate_create / validate_update
      - before_save / after_save
      - before_delete / after_delete

    Notes:
      - No list/get here (you handle read elsewhere)
      - Supports bulk create/update/delete
      - Company + Branch scoping enforcement
      - Safe serialization (columns-only) + DD-MM-YYYY dates
    """

    def __init__(
        self,
        model: Type[T],
        session: Optional[Session] = None,
        repo_cls: Type[BaseEducationRepo] = BaseEducationRepo,
        *,
        tx_mode: TxMode = "service",
        public_fields: Optional[List[str]] = None,
        expire_on_commit_safe: bool = True,
    ):
        self.model = model
        self.s: Session = session or db.session
        self.repo: BaseEducationRepo[T] = repo_cls(model, self.s)

        self.tx_mode: TxMode = tx_mode
        self.public_fields = public_fields or ["id", "name", "title", "code"]
        self.expire_on_commit_safe = bool(expire_on_commit_safe)

        self._tenant_aware = hasattr(model, "company_id")
        self._branch_aware = hasattr(model, "branch_id")
        self._has_enabled = hasattr(model, "is_enabled")

    # ---------------- Tx helpers ----------------

    @property
    def _in_nested_tx(self) -> bool:
        try:
            fn = getattr(self.s, "in_nested_transaction", None)
            if callable(fn):
                return bool(fn())
        except Exception:
            pass

        tx = getattr(self.s, "transaction", None)
        if not tx:
            return False
        if getattr(tx, "nested", False):
            return True

        parent = getattr(tx, "parent", None)
        while parent is not None:
            if getattr(parent, "nested", False):
                return True
            parent = getattr(parent, "parent", None)
        return False

    def _commit_or_flush(self) -> None:
        if self.tx_mode == "external":
            self.s.flush()
            return
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback(self) -> None:
        try:
            if self.tx_mode == "external":
                self.s.rollback()
                return
            if self._in_nested_tx:
                return
            self.s.rollback()
        except Exception:
            pass

    # ---------------- Hooks ----------------

    def validate_create(self, *, company_id: int, branch_id: Optional[int], data: Dict[str, Any]) -> Dict[str, Any]:
        return data

    def validate_update(self, *, company_id: int, branch_id: Optional[int], obj: T, data: Dict[str, Any]) -> Dict[str, Any]:
        return data

    def before_save(self, obj: T, *, is_new: bool) -> None:
        return

    def after_save(self, obj: T, *, is_new: bool) -> None:
        return

    def before_delete(self, obj: T) -> None:
        return

    def after_delete(self, obj: T) -> None:
        return

    # ---------------- Scope enforcement ----------------

    def _enforce_scope_payload(self, *, company_id: int, branch_id: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Security + clarity (multi-tenant + multi-branch):
          - If model has company_id: force payload company_id = scope company_id
          - If model has branch_id and branch_id scope is provided:
              - if payload includes branch_id and mismatches => error
              - else set payload branch_id = scope branch_id
        """
        if self._tenant_aware:
            if "company_id" in payload and payload["company_id"] is not None:
                try:
                    sent = int(payload["company_id"])
                except Exception:
                    raise BizValidationError("company_id must be an integer.")
                if sent != int(company_id):
                    raise BizValidationError("company_id in body does not match your active company scope.")
            payload["company_id"] = int(company_id)

        if self._branch_aware and branch_id is not None:
            if "branch_id" in payload and payload["branch_id"] is not None:
                try:
                    sent_b = int(payload["branch_id"])
                except Exception:
                    raise BizValidationError("branch_id must be an integer.")
                if sent_b != int(branch_id):
                    raise BizValidationError("branch_id in body does not match your active branch scope.")
            payload["branch_id"] = int(branch_id)

        return payload

    # ---------------- Serialization ----------------

    def serialize(self, obj: T, *, only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        if not obj:
            return {}

        if self.expire_on_commit_safe:
            # columns-only safe serialization (prevents lazy-loading)
            mapper = sa_inspect(obj.__class__)
            data: Dict[str, Any] = {}
            for col in mapper.columns:
                key = col.key
                data[key] = _format_date_out(_safe_scalar_attr(obj, key))
            return _pick(data, only) if only else data

        # fallback (if you prefer your model methods)
        if hasattr(obj, "to_dict"):
            d = obj.to_dict()
        elif hasattr(obj, "as_dict"):
            d = obj.as_dict()
        else:
            d = {k: v for k, v in getattr(obj, "__dict__", {}).items() if not k.startswith("_")}

        for k in list(d.keys()):
            d[k] = _format_date_out(d[k])

        return _pick(d, only) if only else d

    def serialize_public(self, obj: T) -> Dict[str, Any]:
        full = self.serialize(obj)
        # keep consistent minimal payload
        out: Dict[str, Any] = {}
        for k in self.public_fields:
            if k in full and full[k] is not None:
                out[k] = full[k]
        # always include id if present
        if "id" in full:
            out["id"] = full["id"]
        return out

    # ---------------- CRUD (Write only) ----------------

    def create_doc(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        data: Dict[str, Any],
        return_public: bool = True,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        try:
            payload = self._enforce_scope_payload(company_id=company_id, branch_id=branch_id, payload=dict(data))
            payload = self.validate_create(company_id=company_id, branch_id=branch_id, data=payload)

            obj = self.model(**payload)
            self.before_save(obj, is_new=True)

            self.s.add(obj)
            self.s.flush([obj])

            self.after_save(obj, is_new=True)
            self._commit_or_flush()

            rec = self.serialize_public(obj) if return_public else self.serialize(obj)
            return True, f"{self.model.__name__} created.", {"record": rec}

        except BizValidationError as e:
            self._rollback()
            return False, str(e), None
        except IntegrityError:
            self._rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            self._rollback()
            log.exception("create_doc failed: %s", e)
            return False, "Unexpected error.", None

    def create_many(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        items: List[Dict[str, Any]],
        return_public: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Bulk create (imports):
          - one add_all + one flush
          - returns count + optional public records
        """
        items = items or []
        if not items:
            return True, "Nothing to create.", {"created": 0, "records": []}

        try:
            payloads: List[Dict[str, Any]] = []
            for it in items:
                p = self._enforce_scope_payload(company_id=company_id, branch_id=branch_id, payload=dict(it))
                p = self.validate_create(company_id=company_id, branch_id=branch_id, data=p)
                payloads.append(p)

            objs = self.repo.create_many(payloads)

            # hooks after bulk: call after_save per obj (optional)
            for o in objs:
                self.after_save(o, is_new=True)

            self._commit_or_flush()

            records = [self.serialize_public(o) for o in objs] if return_public else [self.serialize(o) for o in objs]
            return True, f"Created {len(objs)} record(s).", {"created": len(objs), "records": records}

        except BizValidationError as e:
            self._rollback()
            return False, str(e), {"created": 0, "records": []}
        except IntegrityError:
            self._rollback()
            return False, "Database constraint error.", {"created": 0, "records": []}
        except Exception as e:
            self._rollback()
            log.exception("create_many failed: %s", e)
            return False, "Unexpected error.", {"created": 0, "records": []}

    def update_doc(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        obj: T,
        data: Dict[str, Any],
        allow_nulls: bool = True,
        return_public: bool = True,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Single update:
          - You pass obj (because you handle get/detail elsewhere)
          - Uses UNSET to represent "not provided"
        """
        try:
            payload = dict(data)

            # never allow overriding scope fields by body
            if self._tenant_aware:
                payload.pop("company_id", None)
            if self._branch_aware:
                payload.pop("branch_id", None)

            payload = self.validate_update(company_id=company_id, branch_id=branch_id, obj=obj, data=payload)

            for k, v in payload.items():
                if v is UNSET:
                    continue
                if not hasattr(obj, k):
                    continue
                if v is None and not allow_nulls:
                    continue
                setattr(obj, k, v)

            self.before_save(obj, is_new=False)
            self.s.flush([obj])
            self.after_save(obj, is_new=False)

            self._commit_or_flush()

            rec = self.serialize_public(obj) if return_public else self.serialize(obj)
            return True, f"{self.model.__name__} updated.", {"record": rec}

        except BizValidationError as e:
            self._rollback()
            return False, str(e), None
        except IntegrityError:
            self._rollback()
            return False, "Database constraint error.", None
        except Exception as e:
            self._rollback()
            log.exception("update_doc failed: %s", e)
            return False, "Unexpected error.", None

    def update_many(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        ids: List[int],
        data: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Bulk update in one query (fast for admin list pages / imports).
        """
        ids = [int(x) for x in (ids or []) if x]
        if not ids:
            return True, "Nothing to update.", {"updated": 0, "requested": 0}

        # scope fields cannot be updated from here
        payload = dict(data or {})
        if self._tenant_aware:
            payload.pop("company_id", None)
        if self._branch_aware:
            payload.pop("branch_id", None)

        if not payload:
            return True, "Nothing to update.", {"updated": 0, "requested": len(ids)}

        try:
            updated = self.repo.update_many(
                ids,
                payload,
                company_id=int(company_id) if self._tenant_aware else None,
                branch_id=int(branch_id) if (branch_id is not None and self._branch_aware) else None,
            )
            self._commit_or_flush()
            return True, f"Updated {updated} record(s).", {"updated": updated, "requested": len(ids)}

        except IntegrityError:
            self._rollback()
            return False, "Database constraint error.", {"updated": 0, "requested": len(ids)}
        except Exception as e:
            self._rollback()
            log.exception("update_many failed: %s", e)
            return False, "Bulk update failed.", {"updated": 0, "requested": len(ids)}

    # ---------------- Delete (single + bulk) ----------------

    def delete_doc(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        obj: T,
        soft: bool = True,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Single delete: you pass obj (detail page delete).
        Soft-delete respects is_enabled if present.
        """
        try:
            self.before_delete(obj)

            if soft:
                self.repo.soft_delete_obj(obj)
            else:
                self.repo.hard_delete_obj(obj)

            self.after_delete(obj)
            self._commit_or_flush()

            return True, f"{self.model.__name__} deleted.", {"id": getattr(obj, "id", None)}

        except BizValidationError as e:
            self._rollback()
            return False, str(e), None
        except Exception as e:
            self._rollback()
            log.exception("delete_doc failed: %s", e)
            return False, "Unexpected error.", None

    def bulk_delete(
        self,
        *,
        company_id: int,
        branch_id: Optional[int] = None,
        ids: List[int],
        soft: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Bulk delete for list pages:
          - single UPDATE (soft) or single DELETE (hard)
          - respects company + branch scope
        """
        ids = [int(x) for x in (ids or []) if x]
        if not ids:
            return True, "Nothing to delete.", {"deleted": 0, "requested": 0}

        try:
            scope_company = int(company_id) if self._tenant_aware else None
            scope_branch = int(branch_id) if (branch_id is not None and self._branch_aware) else None

            if soft:
                deleted = self.repo.soft_delete_many(ids, company_id=scope_company, branch_id=scope_branch)
            else:
                deleted = self.repo.hard_delete_many(ids, company_id=scope_company, branch_id=scope_branch)

            self._commit_or_flush()
            return True, f"Deleted {deleted} record(s).", {"deleted": deleted, "requested": len(ids)}

        except Exception as e:
            self._rollback()
            log.exception("bulk_delete failed: %s", e)
            return False, "Bulk delete failed.", {"deleted": 0, "requested": len(ids)}