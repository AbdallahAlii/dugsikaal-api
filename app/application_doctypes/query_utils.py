# app/common/query_utils.py
from __future__ import annotations
from typing import Any, Dict, Sequence, Optional, List
from sqlalchemy import and_, or_, asc, desc, ClauseElement
from sqlalchemy.sql import Select
from sqlalchemy.orm.attributes import InstrumentedAttribute

def _is_column(obj: Any) -> bool:
    return isinstance(obj, InstrumentedAttribute) or hasattr(obj, "ilike") or hasattr(obj, "like")

def apply_search(query: Select, search_columns: Sequence[Any], search_value: str | None) -> Select:
    if not search_value:
        return query
    like_expr = f"%{search_value}%"
    cols = [c for c in (search_columns or []) if _is_column(c)]
    if not cols:
        return query
    return query.where(or_(*[c.ilike(like_expr) for c in cols if hasattr(c, "ilike")]))


def apply_sort(q: Select, sort_key: Optional[str], sort_order: Optional[str],
               sort_fields: Dict[str, ClauseElement],
               default_sort: Optional[List[ClauseElement]] = None) -> Select:
    """
    Apply sorting to a SQLAlchemy Select.

    Behavior:
    1) If user provided sort_key and it exists in sort_fields -> use that (respect sort_order).
    2) Else if default_sort is provided and non-empty -> apply default_sort (in given order).
    3) Else attempt a date-priority auto-detect across known names in sort_fields.
    4) Else fallback to first available sort_field desc.
    """
    # 1) explicit user sort
    if sort_key and sort_key in (sort_fields or {}):
        col = sort_fields[sort_key]
        direction = desc if (sort_order or "").strip().lower() == "desc" else asc
        return q.order_by(direction(col))

    # 2) explicit default_sort from config (highest priority after user choice)
    if default_sort:
        # default_sort should be a list of ClauseElements or (col,) etc.
        # We'll apply them in the given order.
        for s in default_sort:
            q = q.order_by(s)
        return q

    # 3) date-priority heuristic (back-compat)
    date_priority = ['posting_date', 'created_at', 'modified', 'updated_at', 'date']
    for date_field in date_priority:
        if date_field in (sort_fields or {}):
            date_col = sort_fields[date_field]
            q = q.order_by(desc(date_col))
            if 'id' in (sort_fields or {}):
                q = q.order_by(desc(sort_fields['id']))
            return q

    # 4) fallback to first available field (desc)
    if sort_fields:
        first_col = next(iter(sort_fields.values()))
        return q.order_by(desc(first_col))

    return q

def apply_filters_sa(query: Select, filters: Dict[str, Any] | None, allowed_columns: Dict[str, Any] | None) -> Select:
    if not filters or not allowed_columns:
        return query
    conditions = []
    for field, condition in filters.items():
        col = allowed_columns.get(field)
        if col is None:
            continue

        if isinstance(condition, (list, tuple)) and len(condition) == 2:
            op, value = condition
        else:
            op, value = "=", condition

        op = (op or "=").lower()

        if isinstance(value, str):
            lv = value.strip().lower()
            if lv in ("true", "false"):
                value = (lv == "true")

        enum_cls = getattr(getattr(col, "type", None), "enum_class", None)
        if enum_cls and isinstance(value, str):
            for m in enum_cls:
                if value.lower() == str(getattr(m, "value", "")).lower() or value.upper() == m.name:
                    value = m
                    break

        ops = {
            "=": lambda c, v: c == v,
            "!=": lambda c, v: c != v,
            ">": lambda c, v: c > v,
            "<": lambda c, v: c < v,
            ">=": lambda c, v: c >= v,
            "<=": lambda c, v: c <= v,
            "in": lambda c, v: c.in_(v if isinstance(v, (list, tuple, set)) else [v]),
            "not in": lambda c, v: ~c.in_(v if isinstance(v, (list, tuple, set)) else [v]),
            "like": lambda c, v: c.like(f"%{v}%"),
            "not like": lambda c, v: ~c.like(f"%{v}%"),
        }

        if op in ops:
            conditions.append(ops[op](col, value))

    if conditions:
        query = query.where(and_(*conditions))
    return query
