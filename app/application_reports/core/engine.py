# app/application_reports/core/engine.py
from __future__ import annotations
import logging
import time
import os
from typing import Dict, Any, List, Optional, Protocol, TypedDict
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


@dataclass
class ReportMeta:
    name: str
    description: str
    report_type: ReportType
    module: str
    category: str
    version: str = "1.0.0"
    is_standard: bool = True


class BaseReport(ABC):
    def __init__(self, meta: ReportMeta):
        self.meta = meta

    @abstractmethod
    def get_columns(self, filters: Optional[Dict[str, Any]] = None) -> List[ColumnDefinition]:
        pass

    @abstractmethod
    def execute(self, filters: Dict[str, Any], session: Session, context: AffiliationContext) -> ReportResult:
        pass

    def get_filters(self) -> List[FilterDefinition]:
        return []

    def get_chart(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None

    def get_report_summary(self, data: List[Dict[str, Any]], filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return None

    def validate_filters(self, filters: Dict[str, Any]) -> None:
        pass


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

        # Ensure all bind parameters are present
        self._ensure_all_bind_params(filters)

        start_time = time.time()

        try:
            compiled_query = text(self._sql_query)
            result = session.execute(compiled_query, filters)
            data = [dict(row._mapping) for row in result]

            execution_time = time.time() - start_time

            return {
                "columns": self.get_columns(filters),
                "data": data,
                "filters": filters,
                "report_name": self.meta.name,
                "execution_time": execution_time,
                "total_count": len(data),
                "summary": self.get_report_summary(data, filters),
                "chart": self.get_chart(data, filters)
            }

        except Exception as e:
            log.error(f"Query report execution failed for {self.meta.name}: {e}", exc_info=True)
            raise

    def _get_dynamic_columns(self, filters: Dict[str, Any]) -> List[ColumnDefinition]:
        return self._base_columns

    def _apply_default_filters(self, filters: Dict[str, Any], context: AffiliationContext) -> None:
        if 'company' not in filters:
            company_id = getattr(context, 'company_id', None)
            if company_id:
                filters['company'] = str(company_id)

        if 'from_date' not in filters:
            filters['from_date'] = date.today().replace(day=1)

        if 'to_date' not in filters:
            filters['to_date'] = date.today()

    def _load_sql_query(self) -> None:
        try:
            with open(self.sql_file, 'r', encoding='utf-8') as f:
                self._sql_query = f.read()
            # Extract bind parameters from SQL
            self._bind_parameters = self._extract_bind_parameters(self._sql_query)
            log.debug(f"Loaded SQL query from {self.sql_file} with parameters: {self._bind_parameters}")
        except FileNotFoundError:
            raise ValueError(f"SQL file not found: {self.sql_file}")
        except Exception as e:
            raise ValueError(f"Error loading SQL file {self.sql_file}: {e}")

    def _extract_bind_parameters(self, sql_query: str) -> set:
        """Extract bind parameter names from SQL query"""
        # Match :param style parameters (SQLAlchemy)
        colon_params = set(re.findall(r':(\w+)', sql_query))
        # Match %(param)s style parameters (psycopg2)
        percent_params = set(re.findall(r'%\((\w+)\)s', sql_query))
        return colon_params.union(percent_params)

    def _ensure_all_bind_params(self, filters: Dict[str, Any]) -> None:
        """Ensure all bind parameters from SQL are present in filters"""
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
            return self.script_class.get_columns(filters)
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

            return {
                "columns": result.get("columns", self.get_columns(filters)),
                "data": result.get("data", []),
                "filters": filters,
                "report_name": self.meta.name,
                "execution_time": execution_time,
                "total_count": len(result.get("data", [])),
                "summary": result.get("summary"),
                "chart": result.get("chart")
            }

        except Exception as e:
            log.error(f"Script report execution failed for {self.meta.name}: {e}", exc_info=True)
            raise


class ReportEngine:
    def __init__(self, session: Session):
        self.session = session
        self._reports: Dict[str, BaseReport] = {}
        self._report_meta: Dict[str, ReportMeta] = {}

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
        except Exception as e:
            log.error(f"Report execution failed: {name}", exc_info=True)
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
                "version": meta.version
            })

        return reports


def _enhance_gl_filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced filter processing for General Ledger to handle both old and new filtering patterns.
    """
    enhanced_filters = filters.copy()

    # If voucher_no is provided and looks like a source document code (PR-2025-00041, SI-2025-0001, etc.)
    voucher_no = enhanced_filters.get('voucher_no')
    if voucher_no and not enhanced_filters.get('source_document'):
        # Check if it matches source document pattern
        if any(voucher_no.startswith(prefix) for prefix in ['PR-', 'PI-', 'SI-', 'SE-', 'PQ-']):
            enhanced_filters['source_document'] = voucher_no
            # Don't remove voucher_no filter as it might also match journal entry codes

    return enhanced_filters

def create_report_engine(session: Session) -> ReportEngine:
    return ReportEngine(session)