
# app/application_reports/core/engine.py
from __future__ import annotations
import logging
import time
from typing import Dict, Any, List, Optional, TypedDict
from datetime import datetime, date
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import re

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


class ReportType(Enum):
    QUERY = "query"
    SCRIPT = "script"
    BUILDER = "builder"


class ColumnDefinition(TypedDict):
    fieldname: str
    label: str
    fieldtype: str
    options: Optional[str]
    width: Optional[int]
    align: Optional[str]
    precision: Optional[int]
    hidden: Optional[bool]


class FilterDefinition(TypedDict):
    fieldname: str
    label: str
    fieldtype: str
    options: Optional[str]
    default: Optional[Any]
    required: Optional[bool]
    depends_on: Optional[str]


class ReportResult(TypedDict):
    columns: List[ColumnDefinition]
    data: List[Dict[str, Any]]
    filters: Dict[str, Any]
    report_name: str
    execution_time: float
    total_count: int
    summary: Optional[Dict[str, Any]]
    chart: Optional[Dict[str, Any]]
    # pagination
    has_more: Optional[bool]
    next_cursor: Optional[str]


@dataclass
class ReportMeta:
    name: str
    description: str
    report_type: ReportType
    module: str
    category: str
    version: str = "1.0.0"
    is_standard: bool = True
    # per-report cache controls
    cache_enabled: Optional[bool] = None
    cache_ttl_s: Optional[int] = None


class BaseReport(ABC):
    def __init__(self, meta: ReportMeta):
        self.meta = meta

    @abstractmethod
    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        ...

    @abstractmethod
    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        ...

    def get_filters(self) -> List[FilterDefinition]:
        return []

    def get_chart(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None

    def get_report_summary(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        pass


def _normalize_paging(filters: Dict[str, Any]) -> tuple[int, Optional[int]]:
    """
    Returns (limit, offset). Accepts limit/offset or page_length/start (Frappe style).
    Enforces sane defaults and caps.
    """
    HARD_MAX = 500
    DEFAULT = 20

    limit = filters.get('limit')
    page_length = filters.get('page_length')
    if (limit in (None, 0, '')) and page_length not in (None, ''):
        limit = page_length
    try:
        limit = int(limit) if limit not in (None, '') else DEFAULT
    except Exception:
        limit = DEFAULT
    limit = max(1, min(limit, HARD_MAX))

    offset = filters.get('offset')
    start = filters.get('start')
    if (offset in (None, '')) and start not in (None, ''):
        offset = start
    try:
        offset = int(offset) if offset not in (None, '') else None
    except Exception:
        offset = None

    return limit, offset


def _wrap_sql_with_paging(sql: str, order_clause: Optional[str], limit: int, offset: Optional[int], add_one: bool) -> str:
    """
    Wrap original SQL only if it doesn't already contain a LIMIT.
    Adds ORDER BY if provided and missing.
    """
    low = sql.lower()
    if ' limit ' in low or low.strip().endswith(' limit'):
        return sql

    final_sql = f"SELECT * FROM ( {sql} ) _rpt_"
    if order_clause and ' order by ' not in low:
        final_sql += f" ORDER BY {order_clause}"
    lmt = limit + 1 if add_one else limit
    final_sql += f" LIMIT {lmt}"
    if offset is not None:
        final_sql += f" OFFSET {offset}"
    return final_sql


class QueryReport(BaseReport):
    def __init__(self, meta: ReportMeta, sql_file: str, columns: List[ColumnDefinition] = None):
        super().__init__(meta)
        self.sql_file = sql_file
        self._base_columns = columns or []
        self._sql_query: Optional[str] = None
        self._dynamic_columns: bool = columns is None
        self._bind_parameters: Optional[set] = None

    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        if self._dynamic_columns and filters:
            return self._get_dynamic_columns(filters)
        return self._base_columns

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        if self._sql_query is None:
            self._load_sql_query()

        self.validate_filters(filters)
        self._apply_default_filters(filters, context)

        self._ensure_all_bind_params(filters)

        # paging
        limit, offset = _normalize_paging(filters)

        # ordering
        sort = (filters.get('sort') or '').strip()
        order = (filters.get('order') or 'asc').strip().lower()
        if order not in ('asc', 'desc'):
            order = 'asc'

        if sort:
            default_order_clause = f"{sort} {order}, id ASC"
        else:
            # safe default for accounting-like rows
            default_order_clause = "posting_date ASC, voucher_no ASC"

        cursor = filters.get('cursor')
        add_one = True
        compiled_sql = self._sql_query

        # We do not auto-inject keyset WHERE because keys differ per report.
        if cursor:
            # If author added cursor WHERE in SQL, fine; else we fall back to offset (offset ignored here).
            offset = None

        compiled_sql = _wrap_sql_with_paging(compiled_sql, default_order_clause, limit, offset, add_one)

        start_time = time.time()
        try:
            result = session.execute(text(compiled_sql), filters)
            rows = [dict(row._mapping) for row in result]

            has_more = False
            if len(rows) > limit:
                has_more = True
                rows = rows[:limit]

            execution_time = time.time() - start_time

            return {
                "columns": self.get_columns(filters),
                "data": rows,
                "filters": filters,
                "report_name": self.meta.name,
                "execution_time": execution_time,
                "total_count": len(rows),  # page count
                "summary": self.get_report_summary(rows, filters),
                "chart": self.get_chart(rows, filters),
                "has_more": has_more,
                "next_cursor": None,
            }

        except Exception as e:
            log.error(f"Query report execution failed for {self.meta.name}: {e}", exc_info=True)
            raise

    def _get_dynamic_columns(self, filters: Dict[str, Any]) -> List[ColumnDefinition]:
        return self._base_columns

    def _apply_default_filters(self, filters: Dict[str, Any], context: AffiliationContext) -> None:
        # Ensure company is INT
        if 'company' not in filters:
            company_id = getattr(context, 'company_id', None)
            if company_id is not None:
                try:
                    filters['company'] = int(company_id)
                except Exception:
                    filters['company'] = company_id
        else:
            try:
                filters['company'] = int(filters['company'])
            except Exception:
                log.warning("company filter not int-convertible: %s", filters.get('company'))

        if 'from_date' not in filters:
            filters['from_date'] = date.today().replace(day=1)
        if 'to_date' not in filters:
            filters['to_date'] = date.today()

    def _load_sql_query(self) -> None:
        try:
            with open(self.sql_file, 'r', encoding='utf-8') as f:
                self._sql_query = f.read()
            self._bind_parameters = self._extract_bind_parameters(self._sql_query)
            log.debug(f"Loaded SQL query from {self.sql_file} with parameters: {self._bind_parameters}")
        except FileNotFoundError:
            raise ValueError(f"SQL file not found: {self.sql_file}")
        except Exception as e:
            raise ValueError(f"Error loading SQL file {self.sql_file}: {e}")

    # def _extract_bind_parameters(self, sql_query: str) -> set:
    #     colon_params = set(re.findall(r':(\w+)', sql_query))
    #     percent_params = set(re.findall(r'%\((\w+)\)s', sql_query))
    #     return colon_params.union(percent_params)
    def _extract_bind_parameters(self, sql_query: str) -> set[str]:
        try:
            stmt = text(sql_query)

            # Prefer compiled params (less "private" than _bindparams)
            try:
                return set(stmt.compile().params.keys())
            except Exception:
                return set(stmt._bindparams.keys())  # fallback

        except Exception:
            # last-resort fallback to regex (keeps system resilient)
            colon_params = set(re.findall(r':(\w+)', sql_query))
            percent_params = set(re.findall(r'%\((\w+)\)s', sql_query))
            return colon_params.union(percent_params)

    def _ensure_all_bind_params(self, filters: Dict[str, Any]) -> None:
        if not self._bind_parameters:
            return
        for param in self._bind_parameters:
            if param not in filters:
                filters[param] = None
                log.debug(f"Added missing bind parameter '{param}' with value None to filters.")


class ScriptReport(BaseReport):
    def __init__(self, meta: ReportMeta, script_class):
        super().__init__(meta)
        self.script_class = script_class
        self._script_instance: Optional[Any] = None

    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        if hasattr(self.script_class, 'get_columns'):
            try:
                # Try to call as class method first
                return self.script_class.get_columns(filters)
            except AttributeError as e:
                # If it fails with instance method error, create instance
                if "'dict' object has no attribute" in str(e) or \
                        "'type' object has no attribute" in str(e):
                    if self._script_instance is None:
                        # Create instance with default parameters
                        try:
                            # Try to create instance with minimal params
                            self._script_instance = self.script_class()
                        except TypeError:
                            # If constructor needs params, provide defaults
                            from app.application_reports.core.accounting_utils import ReportAccountTypeEnum
                            self._script_instance = self.script_class(
                                account_type=ReportAccountTypeEnum.RECEIVABLE,
                                is_summary=True
                            )
                    return self._script_instance.get_columns(filters)
                raise
        return []

    def get_filters(self) -> List[FilterDefinition]:
        if hasattr(self.script_class, 'get_filters'):
            return self.script_class.get_filters()
        return super().get_filters()

    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        try:
            if self._script_instance is None:
                self._script_instance = self.script_class()

            start_time = time.time()
            result = self._script_instance.execute(filters, session, context)
            execution_time = time.time() - start_time

            # === NEW: generic paging for Script reports (offset-based) ===
            limit, offset = _normalize_paging(filters)
            data = result.get("data", []) or []
            has_more = result.get("has_more")
            next_cursor = result.get("next_cursor")

            # If the script didn't implement paging/cursor, enforce offset/limit here.
            if has_more is None and next_cursor is None:
                start_idx = 0 if offset is None else max(0, int(offset))
                end_idx = start_idx + int(limit)
                page = data[start_idx:end_idx]
                # has_more true only if we actually had more beyond end_idx
                has_more = len(data) > end_idx
                data = page
                # leave next_cursor as None in offset mode

            return {
                "columns": result.get("columns", self.get_columns(filters)),
                "data": data,
                "filters": filters,
                "report_name": self.meta.name,
                "execution_time": execution_time,
                "total_count": len(data),  # page count, not total in DB
                "summary": result.get("summary"),
                "chart": result.get("chart"),
                "has_more": has_more,
                "next_cursor": next_cursor,
            }

        except Exception as e:
            log.error(f"Script report execution failed for {self.meta.name}: {e}", exc_info=True)
            raise


class ReportEngine:
    def __init__(self, session: Session):
        self.session = session
        self._reports: Dict[str, BaseReport] = {}
        the_meta: Dict[str, ReportMeta] = {}
        self._report_meta = the_meta  # keep attribute name stable

    def register_report(self, report: BaseReport) -> None:
        name = report.meta.name
        self._reports[name] = report
        self._report_meta[name] = report.meta
        log.info(f"📊 Registered report: {name} ({report.meta.report_type.value})")

    def execute_report(self, name: str, filters: Dict[str, Any], context: AffiliationContext) -> ReportResult:
        if name not in self._reports:
            raise ValueError(f"Report '{name}' not found. Available: {list(self._reports.keys())}")
        report = self._reports[name]
        try:
            return report.execute(filters, self.session, context)
        except Exception:
            log.error("Report execution failed: %s", name, exc_info=True)
            raise

    def get_report_meta(self, name: str) -> ReportMeta:
        if name not in self._report_meta:
            raise ValueError(f"Report '{name}' not found")
        return self._report_meta[name]

    def get_report_columns(self, name: str, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        if name not in self._reports:
            raise ValueError(f"Report '{name}' not found")
        return self._reports[name].get_columns(filters)

    def get_report_filters(self, name: str) -> List[FilterDefinition]:
        if name not in self._reports:
            raise ValueError(f"Report '{name}' not found")
        return self._reports[name].get_filters()

    def list_reports(self, module: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        reports = []
        for name, meta in self._report_meta.items():
            if module and meta.module != module:
                continue
            if category and meta.category != category:
                continue
            reports.append({
                "name": name,
                "description": meta.description,
                "type": meta.report_type.value,
                "module": meta.module,
                "category": meta.category,
                "is_standard": meta.is_standard,
                "version": meta.version,
                "cache_enabled": meta.cache_enabled,
                "cache_ttl_s": meta.cache_ttl_s,
            })
        return reports


def create_report_engine(session: Session) -> ReportEngine:
    return ReportEngine(session)
