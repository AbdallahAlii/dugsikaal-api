# app/common/query_utils.py
from __future__ import annotations
from typing import Any, Dict, Sequence
from sqlalchemy import and_, or_, asc, desc
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

def apply_sort(query: Select, sort_key: str | None, sort_order: str | None, sort_fields: Dict[str, Any]) -> Select:
    col = sort_fields.get((sort_key or "").strip())
    if not col:
        if sort_fields:
            col = next(iter(sort_fields.values()))
        else:
            return query
    direction = desc if (sort_order or "").strip().lower() == "desc" else asc
    return query.order_by(direction(col))

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
