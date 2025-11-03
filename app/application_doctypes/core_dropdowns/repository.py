# # app/application_doctypes/core_dropdowns/repository.py

from __future__ import annotations
import logging
from typing import Any, Dict, Mapping, Optional, List
from sqlalchemy import select, func
from sqlalchemy.sql import Select

from config.database import db
from app.application_doctypes import query_utils
from .config import get_dropdown_config, DropdownConfig
from .cache import build_dropdown_scope_key
from app.common.cache import api as cache_api
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)

def _format_rows(rows: List[Mapping]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for r in rows:
        d = dict(r)
        value = d.pop("value", None)
        label = d.pop("label", None)
        if value is None or label is None:
            continue
        key = (value, label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"value": value, "label": label, "meta": d})
    return out

class DropdownRepository:
    def get_options(
        self,
        *,
        module_name: str,
        name: str,
        user_context: AffiliationContext,
        q: Optional[str],
        limit: int,
        offset: int,
        params: Mapping[str, Any],   # deps/filters/flat params
        fresh: bool = False,
        sort: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Dict[str, Any]:
        cfg: DropdownConfig = get_dropdown_config(module_name, name)

        # Clamp window when q is empty (nice UX on huge tables)
        if (not q) and cfg.window_when_empty:
            limit = min(limit, int(cfg.window_when_empty))

        params_for_cache = {
            "q": q or "",
            "limit": int(limit),
            "offset": int(offset),
            "filters": dict(params or {}),
            "sort": (sort or "").strip(),
            "order": (order or "").strip().lower(),
        }

        scope_key = build_dropdown_scope_key(cfg, user_context, params=params_for_cache)

        log.info(
            "[dropdowns] READ module=%s name=%s scope=%s scope_enum=%s q=%r limit=%s offset=%s filters=%s sort=%s order=%s",
            module_name, name, scope_key, getattr(cfg.cache_scope, "value", cfg.cache_scope),
            q, limit, offset, params_for_cache["filters"], params_for_cache["sort"], params_for_cache["order"]
        )

        def _builder():
            # IMPORTANT: call builder POSITIONALLY to avoid ctx/context kwarg mismatch
            sel: Select = cfg.query_builder(db.session, user_context, params_for_cache["filters"])

            # Search + filters + optional sort
            sel = query_utils.apply_search(sel, cfg.search_fields, q)
            sel = query_utils.apply_filters_sa(sel, params_for_cache["filters"], cfg.filter_fields)
            if cfg.sort_fields:
                sel = query_utils.apply_sort(sel, sort, order, cfg.sort_fields)

            # Count total
            count_q = select(func.count()).select_from(sel.order_by(None).subquery())
            total_items = db.session.execute(count_q).scalar_one()

            # Page
            final_q = sel.offset(offset).limit(limit)
            rows = db.session.execute(final_q).mappings().all()
            data = _format_rows(rows)
            has_more = (offset + limit) < total_items

            log.debug("[dropdowns] DB BUILT module=%s name=%s rows=%s total=%s",
                      module_name, name, len(data), total_items)
            return {"data": data, "total": total_items, "has_more": has_more}

        # Respect fresh and cfg.cache_enabled
        if fresh or not cfg.cache_enabled:
            return _builder()

        return cache_api.get_dropdown_options(
            module_name=module_name,
            name=name,
            scope_key=scope_key,
            params=params_for_cache,
            builder=_builder,
            ttl=cfg.cache_ttl,
            enabled=cfg.cache_enabled,
        )

dropdown_repository = DropdownRepository()
