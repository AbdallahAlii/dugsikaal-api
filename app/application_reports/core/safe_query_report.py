# from __future__ import annotations
# import logging
# from typing import Dict, Any, Iterable, List, Optional, Callable
#
# from sqlalchemy.orm import Session
# from sqlalchemy import text
#
# from app.application_reports.core.engine import QueryReport, ColumnDefinition, ReportResult
# from app.security.rbac_effective import AffiliationContext
# from config.database import db
#
# log = logging.getLogger(__name__)
#
# class SafeQueryReport(QueryReport):
#     """
#     QueryReport + required-filter validation + optional dynamic columns
#     + preflight resolution for item/warehouse with friendly errors.
#     """
#     def __init__(
#         self, *args,
#         required_all: Optional[Iterable[str]] = None,
#         required_any_groups: Optional[List[Iterable[str]]] = None,
#         columns_selector: Optional[Callable[[Dict[str, Any]], List[ColumnDefinition]]] = None,
#         **kwargs
#     ):
#         super().__init__(*args, **kwargs)
#         self._required_all = list(required_all or [])
#         self._required_any_groups = [list(g) for g in (required_any_groups or [])]
#         self._columns_selector = columns_selector
#
#     # ---------- helpers ------------------------------------------------------
#
#     @staticmethod
#     def _missing(v: Any) -> bool:
#         return v is None or (isinstance(v, str) and v.strip() == "")
#
#     def _resolve_item_id(self, company: int, filters: Dict[str, Any]) -> Optional[int]:
#         if filters.get("item_id"):
#             return int(filters["item_id"])
#         if not filters.get("item"):
#             return None
#         row = db.session.execute(
#             text("""
#                 SELECT i.id
#                 FROM items i
#                 WHERE i.company_id = :company
#                   AND (i.sku = :item OR i.name = :item)
#                 LIMIT 1
#             """),
#             {"company": company, "item": filters["item"]}
#         ).first()
#         return row[0] if row else None
#
#     def _resolve_warehouse_id(self, company: int, filters: Dict[str, Any]) -> Optional[int]:
#         if filters.get("warehouse_id"):
#             return int(filters["warehouse_id"])
#         if not filters.get("warehouse"):
#             return None
#         row = db.session.execute(
#             text("""
#                 SELECT w.id
#                 FROM warehouses w
#                 WHERE w.company_id = :company
#                   AND (w.code = :warehouse OR w.name = :warehouse)
#                 LIMIT 1
#             """),
#             {"company": company, "warehouse": filters["warehouse"]}
#         ).first()
#         return row[0] if row else None
#
#     def _exists_any_stock_record(
#         self, company: int, item_id: int, warehouse_id: int, branch_id: Optional[int]
#     ) -> bool:
#         # Prefer a quick existence check on Bins first (fast, indexed)
#         row = db.session.execute(
#             text("""
#                 SELECT 1
#                 FROM bins
#                 WHERE company_id = :company
#                   AND item_id = :item_id
#                   AND warehouse_id = :warehouse_id
#                 LIMIT 1
#             """),
#             {"company": company, "item_id": item_id, "warehouse_id": warehouse_id}
#         ).first()
#         if row:
#             return True
#
#         # Fall back to a very cheap SLE existence check (uses your indexes)
#         row = db.session.execute(
#             text("""
#                 SELECT 1
#                 FROM stock_ledger_entries sle
#                 WHERE sle.company_id = :company
#                   AND sle.item_id = :item_id
#                   AND sle.warehouse_id = :warehouse_id
#                   AND (:branch_id IS NULL OR sle.branch_id = :branch_id)
#                 LIMIT 1
#             """),
#             {
#                 "company": company,
#                 "item_id": item_id,
#                 "warehouse_id": warehouse_id,
#                 "branch_id": branch_id,
#             }
#         ).first()
#         return bool(row)
#
#     # ---------- validation ---------------------------------------------------
#
#     def validate_filters(self, filters: Dict[str, Any]) -> None:
#         # required_all
#         missing_all = [k for k in self._required_all if self._missing(filters.get(k))]
#         if missing_all:
#             raise ValueError(f"Missing required filters: {', '.join(missing_all)}")
#
#         # required_any_groups
#         for group in self._required_any_groups:
#             if all(self._missing(filters.get(k)) for k in group):
#                 raise ValueError(f"Provide at least one of: {', '.join(group)}")
#
#         # ---- Pre-resolve & friendly errors (company scope is guaranteed) ----
#         try:
#             company = int(filters["company"])
#         except Exception:
#             raise ValueError("Invalid company id")
#
#         # Resolve item_id and warehouse_id if only codes/names sent
#         item_id = self._resolve_item_id(company, filters)
#         wh_id   = self._resolve_warehouse_id(company, filters)
#
#         # Mirror what the SQL expects: at least one of each group must be present
#         if self._missing(item_id):
#             if filters.get("item"):
#                 raise ValueError(f"Item not found in company {company}: {filters['item']}")
#             else:
#                 raise ValueError("Missing item_id or item")
#
#         if self._missing(wh_id):
#             if filters.get("warehouse"):
#                 raise ValueError(f"Warehouse not found in company {company}: {filters['warehouse']}")
#             else:
#                 raise ValueError("Missing warehouse_id or warehouse")
#
#         # Put the resolved IDs back into filters so the SQL sees them
#         filters["item_id"] = item_id
#         filters["warehouse_id"] = wh_id
#
#         # Optional branch typed as int if present
#         branch_id = None
#         if filters.get("branch_id") not in (None, "", "null"):
#             try:
#                 branch_id = int(filters.get("branch_id"))
#                 filters["branch_id"] = branch_id
#             except Exception:
#                 raise ValueError("Invalid branch_id")
#
#         # If no stock records exist at all for this (item, warehouse[, branch]),
#         # return a clear ERP-style message instead of 500.
#         if not self._exists_any_stock_record(company, item_id, wh_id, branch_id):
#             # You can relax this to a zero-row response by removing this error.
#             raise ValueError(
#                 f"No stock records for item_id={item_id} in warehouse_id={wh_id} (company={company})"
#                 + (f" and branch_id={branch_id}" if branch_id is not None else "")
#             )
#
#     # ---------- dynamic columns ---------------------------------------------
#
#     def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
#         if self._columns_selector and filters is not None:
#             return self._columns_selector(filters)
#         return super().get_columns(filters)
#
#     # ---------- execute with guard ------------------------------------------
#
#     def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
#         try:
#             self.validate_filters(filters)
#             return super().execute(filters, session, context)
#         except ValueError as e:
#             log.error(f"Filter validation failed for {self.meta.name}: {e}")
#             raise
#         except Exception as e:
#             log.error(f"Report execution failed for {self.meta.name}: {e}", exc_info=True)
#             raise
# app/application_reports/core/safe_query_report.py
from __future__ import annotations
import logging
from typing import Dict, Any, Iterable, List, Optional, Callable, Sequence

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.application_reports.core.engine import QueryReport, ColumnDefinition, ReportResult
from app.security.rbac_effective import AffiliationContext
from config.database import db

log = logging.getLogger(__name__)

class SafeQueryReport(QueryReport):
    """
    QueryReport + required-filter validation + optional dynamic columns,
    with friendly pre-resolution of item/warehouse and ERP-style messages.

    NOTE: Whether item / warehouse are required is controlled by
    `required_all` / `required_any_groups` passed at registration time.
    This class *does not* force warehouse unless configured to.
    """

    def __init__(
        self, *args,
        required_all: Optional[Iterable[str]] = None,
        required_any_groups: Optional[List[Iterable[str]]] = None,
        columns_selector: Optional[Callable[[Dict[str, Any]], List[ColumnDefinition]]] = None,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._required_all = list(required_all or [])
        self._required_any_groups: List[List[str]] = [list(g) for g in (required_any_groups or [])]
        self._columns_selector = columns_selector

    # ---------- helpers ------------------------------------------------------

    @staticmethod
    def _missing(v: Any) -> bool:
        return v is None or (isinstance(v, str) and v.strip() == "")

    def _resolve_item_id(self, company: int, filters: Dict[str, Any]) -> Optional[int]:
        if filters.get("item_id"):
            return int(filters["item_id"])
        if not filters.get("item"):
            return None
        row = db.session.execute(
            text("""
                SELECT i.id
                FROM items i
                WHERE i.company_id = :company
                  AND (i.sku = :item OR i.name = :item)
                LIMIT 1
            """),
            {"company": company, "item": filters["item"]}
        ).first()
        return row[0] if row else None

    def _resolve_warehouse_id(self, company: int, filters: Dict[str, Any]) -> Optional[int]:
        if filters.get("warehouse_id"):
            return int(filters["warehouse_id"])
        if not filters.get("warehouse"):
            return None
        row = db.session.execute(
            text("""
                SELECT w.id
                FROM warehouses w
                WHERE w.company_id = :company
                  AND (w.code = :warehouse OR w.name = :warehouse)
                LIMIT 1
            """),
            {"company": company, "warehouse": filters["warehouse"]}
        ).first()
        return row[0] if row else None

    def _exists_any_stock_record_pair(
        self, company: int, item_id: int, warehouse_id: int, branch_id: Optional[int]
    ) -> bool:
        # quick bin check
        row = db.session.execute(
            text("""
                SELECT 1
                FROM bins
                WHERE company_id = :company
                  AND item_id = :item_id
                  AND warehouse_id = :warehouse_id
                LIMIT 1
            """),
            {"company": company, "item_id": item_id, "warehouse_id": warehouse_id}
        ).first()
        if row:
            return True

        # cheap SLE existence check
        row = db.session.execute(
            text("""
                SELECT 1
                FROM stock_ledger_entries sle
                WHERE sle.company_id = :company
                  AND sle.item_id = :item_id
                  AND sle.warehouse_id = :warehouse_id
                  AND (:branch_id IS NULL OR sle.branch_id = :branch_id)
                LIMIT 1
            """),
            {
                "company": company,
                "item_id": item_id,
                "warehouse_id": warehouse_id,
                "branch_id": branch_id,
            }
        ).first()
        return bool(row)

    def _exists_any_stock_record_any_warehouse(
        self, company: int, item_id: int, branch_id: Optional[int]
    ) -> bool:
        # any bin
        row = db.session.execute(
            text("""
                SELECT 1
                FROM bins
                WHERE company_id = :company
                  AND item_id = :item_id
                LIMIT 1
            """),
            {"company": company, "item_id": item_id}
        ).first()
        if row:
            return True

        # any SLE
        row = db.session.execute(
            text("""
                SELECT 1
                FROM stock_ledger_entries sle
                WHERE sle.company_id = :company
                  AND sle.item_id = :item_id
                  AND (:branch_id IS NULL OR sle.branch_id = :branch_id)
                LIMIT 1
            """),
            {"company": company, "item_id": item_id, "branch_id": branch_id}
        ).first()
        return bool(row)

    # ---------- validation ---------------------------------------------------

    def _is_group_required(self, names: Sequence[str]) -> bool:
        """
        Return True if any filter name in `names` is present in any required_any_groups,
        or explicitly in required_all.
        """
        all_set = set(self._required_all)
        any_sets = [set(g) for g in self._required_any_groups]
        if all_set.intersection(names):
            return True
        for s in any_sets:
            if s.intersection(names):
                return True
        return False

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        # required_all
        missing_all = [k for k in self._required_all if self._missing(filters.get(k))]
        if missing_all:
            raise ValueError(f"Missing required filters: {', '.join(missing_all)}")

        # required_any_groups
        for group in self._required_any_groups:
            if all(self._missing(filters.get(k)) for k in group):
                raise ValueError(f"Provide at least one of: {', '.join(group)}")

        # ---- Pre-resolve & friendly errors (company scope is guaranteed) ----
        try:
            company = int(filters["company"])
        except Exception:
            raise ValueError("Invalid company id")

        # Determine whether item and/or warehouse are required for THIS report
        require_item = self._is_group_required(("item_id", "item"))
        require_warehouse = self._is_group_required(("warehouse_id", "warehouse"))

        # Resolve IDs only if provided or required
        item_id = self._resolve_item_id(company, filters) if (require_item or filters.get("item_id") or filters.get("item")) else None
        wh_id   = self._resolve_warehouse_id(company, filters) if (require_warehouse or filters.get("warehouse_id") or filters.get("warehouse")) else None

        if require_item and self._missing(item_id):
            if filters.get("item"):
                raise ValueError(f"Item not found in company {company}: {filters['item']}")
            raise ValueError("Missing item_id or item")

        if require_warehouse and self._missing(wh_id):
            if filters.get("warehouse"):
                raise ValueError(f"Warehouse not found in company {company}: {filters['warehouse']}")
            raise ValueError("Missing warehouse_id or warehouse")

        # Put the resolved IDs back so SQL sees them (leave None if truly optional)
        if item_id is not None:
            filters["item_id"] = item_id
        if wh_id is not None:
            filters["warehouse_id"] = wh_id

        # Optional branch typed as int if present
        branch_id = None
        if filters.get("branch_id") not in (None, "", "null"):
            try:
                branch_id = int(filters.get("branch_id"))
                filters["branch_id"] = branch_id
            except Exception:
                raise ValueError("Invalid branch_id")

        # Existence checks (ERP-style friendly errors). If warehouse is optional
        # and not provided, check "any warehouse" instead of a pair.
        if require_item and item_id is not None:
            if wh_id is not None:
                if not self._exists_any_stock_record_pair(company, item_id, wh_id, branch_id):
                    raise ValueError(
                        f"No stock records for item_id={item_id} in warehouse_id={wh_id} (company={company})"
                        + (f" and branch_id={branch_id}" if branch_id is not None else "")
                    )
            else:
                # warehouse optional: ensure the item has any stock records at all
                if not self._exists_any_stock_record_any_warehouse(company, item_id, branch_id):
                    raise ValueError(
                        f"No stock records for item_id={item_id} in any warehouse (company={company})"
                        + (f" and branch_id={branch_id}" if branch_id is not None else "")
                    )

    # ---------- dynamic columns ---------------------------------------------

    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        if self._columns_selector and filters is not None:
            return self._columns_selector(filters)
        return super().get_columns(filters)

    # ---------- execute with guard ------------------------------------------

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        try:
            self.validate_filters(filters)
            return super().execute(filters, session, context)
        except ValueError as e:
            log.error(f"Filter validation failed for {self.meta.name}: {e}")
            raise
        except Exception as e:
            log.error(f"Report execution failed for {self.meta.name}: {e}", exc_info=True)
            raise
