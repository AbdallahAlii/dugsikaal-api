#
#
# # app/application_doctypes/core_lists/repository.py

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, BadRequest
from sqlalchemy import select, func, and_
from sqlalchemy.sql import Select
from sqlalchemy.engine import Row, MappingResult
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.elements import ColumnElement

from app.common.cache import api as cache_api
from config.database import db
from .config import get_list_config
from .cache import build_list_scope_key
from app.common.cache import api as cache
from .. import query_utils
from app.security.rbac_effective import AffiliationContext
from .config import get_detail_config, DetailConfig

# ------- datetime + SQLA type helpers for date-range filtering -------
from datetime import date as _date, datetime as _dt, timedelta, timezone
from sqlalchemy.sql.sqltypes import Date as SA_Date, DateTime as SA_DateTime, TIMESTAMP as SA_Timestamp

# ✅ absolute import (avoid fragile relative dots)
from app.common.date_utils import parse_date_flex, ACCEPTED_FORMATS_HUMAN

log = logging.getLogger(__name__)

def _row_to_dict(row: Row | MappingResult | dict) -> dict:
    return row if isinstance(row, dict) else dict(row)

APP_TZ = timezone(timedelta(hours=3))  # Africa/Mogadishu (+03:00)


def _parse_date_or_400(val: Any) -> _date:
    d = parse_date_flex(val)
    if d is None:
        raise BadRequest(f"Invalid date. Accepted formats: {ACCEPTED_FORMATS_HUMAN}.")
    return d


def _day_bounds(d: _date) -> tuple[_dt, _dt]:
    start = _dt(d.year, d.month, d.day, 0, 0, 0, tzinfo=APP_TZ)
    return start, start + timedelta(days=1)


def _is_date_like(col: Any) -> bool:
    try:
        return isinstance(getattr(col, "type", None), (SA_Date, SA_DateTime, SA_Timestamp))
    except Exception:
        return False


def _is_date_type(col: Any) -> bool:
    return isinstance(getattr(col, "type", None), SA_Date)


def _resolve_date_field(cfg, filters: Dict[str, Any]) -> Tuple[Optional[str], Optional[ColumnElement]]:
    if not getattr(cfg, "filter_fields", None):
        return None, None

    # Preferred names
    for name in ["posting_date", "date", "transaction_date", "due_date", "created_at", "updated_at"]:
        col = cfg.filter_fields.get(name)
        if col is not None:
            return name, col

    # Fallback: first date-like
    for name, col in cfg.filter_fields.items():
        if _is_date_like(col):
            return name, col

    return None, None


def _extract_date_params(filters: Dict[str, Any], field_name: Optional[str]) -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    exact = filters.get("on_date") or filters.get("date")
    dfrom = filters.get("date_from") or filters.get("from_date")
    dto   = filters.get("date_to") or filters.get("to_date")

    if field_name:
        exact = filters.get(field_name, exact)
        dfrom = filters.get(f"{field_name}_from", dfrom)
        dto   = filters.get(f"{field_name}_to", dto)

    return (exact, dfrom, dto)


def _strip_date_keys(filters: Dict[str, Any], field_name: Optional[str]) -> None:
    for k in ("on_date", "date", "date_from", "date_to", "from_date", "to_date"):
        filters.pop(k, None)
    if field_name:
        filters.pop(field_name, None)
        filters.pop(f"{field_name}_from", None)
        filters.pop(f"{field_name}_to", None)


def _apply_generic_date_filters_if_any(q: Select, cfg, filters: Dict[str, Any]) -> Select:
    field_name, date_col = _resolve_date_field(cfg, filters)
    if date_col is None:
        return q

    exact, dfrom, dto = _extract_date_params(filters, field_name)
    clauses = []
    is_date_column = _is_date_type(date_col)  # True = DATE; False = TIMESTAMP/DateTime

    # Exact date
    if exact is not None and exact != "":
        d = _parse_date_or_400(exact)
        if is_date_column:
            clauses.append(date_col == d)
        else:
            start, end = _day_bounds(d)
            clauses.append(and_(date_col >= start, date_col < end))

    # From
    if dfrom is not None and dfrom != "":
        d = _parse_date_or_400(dfrom)
        if is_date_column:
            clauses.append(date_col >= d)
        else:
            start, _ = _day_bounds(d)
            clauses.append(date_col >= start)

    # To
    if dto is not None and dto != "":
        d = _parse_date_or_400(dto)
        if is_date_column:
            clauses.append(date_col <= d)
        else:
            _, end = _day_bounds(d)
            clauses.append(date_col < end)

    if clauses:
        q = q.where(and_(*clauses))

    # prevent double-filtering by the generic filter pass
    _strip_date_keys(filters, field_name)
    return q


class ListRepository:
    def get_paginated_list(
        self,
        *,
        module_name: str,
        entity_name: str,
        user_context: AffiliationContext,
        page: int,
        per_page: int,
        sort: str,
        order: str,
        search: Optional[str],
        filters: Optional[Dict[str, Any]],
    ):
        cfg = get_list_config(module_name, entity_name)

        params_for_cache = {
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
            "search": search,
            "filters": filters or {},
        }

        scope_key = build_list_scope_key(cfg, user_context, params=params_for_cache)

        log.info(
            "[lists] READ module=%s entity=%s scope=%s scope_enum=%s ctx_company=%s ctx_branch=%s filters=%s search=%r sort=%s order=%s page=%s per_page=%s",
            module_name,
            entity_name,
            scope_key,
            getattr(cfg.cache_scope, "value", cfg.cache_scope),
            getattr(user_context, "company_id", None),
            getattr(user_context, "branch_id", None),
            params_for_cache.get("filters"),
            search,
            sort,
            order,
            page,
            per_page,
        )

        def _build_from_db():
            q: Select = cfg.query_builder(session=db.session, context=user_context)

            # 1) free-text search
            q = query_utils.apply_search(q, cfg.search_fields, search)

            # 2) date filters (generic) — use a local copy
            _filters_local = dict(filters or {})
            q = _apply_generic_date_filters_if_any(q, cfg, _filters_local)

            # 3) remaining filters
            q = query_utils.apply_filters_sa(q, _filters_local, cfg.filter_fields)

            # 4) sort
            q = query_utils.apply_sort(q, sort, order, cfg.sort_fields)

            # 5) count + page
            count_q = select(func.count()).select_from(q.order_by(None).subquery())
            total_items = db.session.execute(count_q).scalar_one()

            final_q = q.offset((page - 1) * per_page).limit(per_page)
            rows = db.session.execute(final_q).mappings().all()
            data = [_row_to_dict(r) for r in rows]

            log.debug("[lists] DB BUILT module=%s entity=%s rows=%s total=%s",
                      module_name, entity_name, len(data), total_items)
            return {"data": data, "total": total_items}

        return cache.get_doctype_list(
            module_name=module_name,
            entity_name=entity_name,
            scope_key=scope_key,
            params=params_for_cache,
            builder=_build_from_db,
            ttl=cfg.cache_ttl,
            enabled=cfg.cache_enabled,
        )

list_repository = ListRepository()


class DetailRepository:
    def _resolve_record_id(
        self, session: Session, cfg: DetailConfig, ctx: AffiliationContext, by: str, ident: str
    ) -> Optional[int]:
        if cfg.resolver_map:
            chosen_by = (by or cfg.default_by)
            if not chosen_by:
                chosen_by = "id" if "id" in cfg.resolver_map else next(iter(cfg.resolver_map.keys()))
            resolver = cfg.resolver_map.get(chosen_by)
            if not resolver:
                raise BadRequest("Unsupported lookup.")
            return resolver(session, ctx, ident)

        if by and by != "id":
            raise BadRequest("Unsupported lookup.")
        try:
            return int(ident)
        except (ValueError, TypeError):
            raise BadRequest("Invalid identifier.")

    def get_document_detail(
        self,
        *,
        module_name: str,
        entity_name: str,
        by: Optional[str],
        identifier: str,
        user_context: AffiliationContext,
        fresh: bool = False,
    ) -> Optional[Dict[str, Any]]:
        cfg = get_detail_config(module_name, entity_name)

        record_id = self._resolve_record_id(db.session, cfg, user_context, by or "", identifier)
        if record_id is None:
            raise NotFound("Not found.")

        log.info("[detail] READ module=%s entity=%s by=%s ident=%s -> id=%s",
                 module_name, entity_name, by or (cfg.default_by or "id"), identifier, record_id)

        def _builder():
            log.debug("[detail] BUILDER_EXEC module=%s entity=%s id=%s",
                      module_name, entity_name, record_id)
            return cfg.loader(db.session, user_context, record_id)

        if not cfg.cache_enabled or fresh:
            return _builder()

        return cache_api.get_doctype_detail(
            module_name=module_name,
            entity_name=entity_name,
            record_id=record_id,
            builder=_builder,
            ttl=cfg.cache_ttl,
            enabled=cfg.cache_enabled,
        )

detail_repository = DetailRepository()
