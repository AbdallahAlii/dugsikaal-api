from __future__ import annotations
import logging
from typing import Dict, List, Callable, Any, Optional, Mapping
from sqlalchemy.sql import Select
from sqlalchemy.orm import Session
from app.security.rbac_effective import AffiliationContext
from app.application_doctypes.core_lists.config import CacheScope  # reuse enum

log = logging.getLogger(__name__)

class DropdownConfig:
    """
    Declarative dropdown configuration.

    query_builder(session, context, params) -> Select
      MUST select columns labeled as: value, label
      Any additional columns will be returned under "meta" for each option.

    Optional helpers (parity with lists):
    - search_fields: columns for fuzzy search
    - sort_fields:   mapping for stable sort keys (used by ?sort/?order)
    - filter_fields: mapping param->column (allow-listed)
    - cache_enabled/cache_ttl/cache_scope: versioned cache controls
    - default_limit/max_limit: UX clamps
    - window_when_empty: when q is empty, clamp limit to this many (nice UX on huge tables)
    """
    def __init__(
        self,
        *,
        permission_tag: str,
        query_builder: Callable[[Session, AffiliationContext, Mapping[str, Any]], Select],
        search_fields: Optional[List[Any]] = None,
        sort_fields: Optional[Dict[str, Any]] = None,
        filter_fields: Optional[Dict[str, Any]] = None,
        cache_enabled: bool = True,
        cache_ttl: int = 600,
        cache_scope: CacheScope = CacheScope.COMPANY,
        default_limit: int = 20,
        max_limit: int = 100,
        window_when_empty: Optional[int] = None,
    ) -> None:
        if not permission_tag or not callable(query_builder):
            raise TypeError("permission_tag and query_builder are required.")

        original = cache_scope
        if not isinstance(cache_scope, CacheScope):
            if isinstance(cache_scope, str):
                try:
                    cache_scope = CacheScope[cache_scope.upper()]
                except KeyError:
                    cache_scope = CacheScope(cache_scope.lower())
            else:
                cache_scope = CacheScope.COMPANY
        if original != cache_scope:
            log.info("[dropdowns] Normalized cache_scope %r -> %r", original, cache_scope)

        self.permission_tag = permission_tag
        self.query_builder = query_builder
        self.search_fields = search_fields or []
        self.sort_fields = sort_fields or {}
        self.filter_fields = filter_fields or {}
        self.cache_enabled = cache_enabled
        self.cache_ttl = int(cache_ttl)
        self.cache_scope = cache_scope
        self.default_limit = int(default_limit)
        self.max_limit = int(max_limit)
        self.window_when_empty = window_when_empty

DROPDOWN_REGISTRY: Dict[str, Dict[str, DropdownConfig]] = {}

def register_dropdown_configs(module_name: str, configs: Dict[str, DropdownConfig]) -> None:
    if module_name not in DROPDOWN_REGISTRY:
        DROPDOWN_REGISTRY[module_name] = {}
    DROPDOWN_REGISTRY[module_name].update(configs)
    for key, cfg in configs.items():
        log.info(
            "[dropdowns] Registered config module=%s name=%s scope=%s ttl=%s cached=%s",
            module_name, key, getattr(cfg.cache_scope, "value", cfg.cache_scope),
            cfg.cache_ttl, cfg.cache_enabled
        )

def get_dropdown_config(module_name: str, name: str) -> DropdownConfig:
    module = DROPDOWN_REGISTRY.get(module_name)
    if not module:
        raise ValueError(f"Module '{module_name}' not found or has no registered dropdowns.")
    cfg = module.get(name)
    if not cfg:
        raise ValueError(f"Dropdown '{name}' not found in module '{module_name}'.")
    return cfg
