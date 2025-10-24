
# app/application_doctypes/core_lists/config.py
from __future__ import annotations
import logging
from enum import Enum
from typing import Dict, List, Callable, Any, Optional

from sqlalchemy.schema import Column
from sqlalchemy.sql import Select
from sqlalchemy.orm import Session
from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)

class CacheScope(str, Enum):
    GLOBAL = "global"
    COMPANY = "company"
    BRANCH  = "branch"

class ListConfig:
    """
    Declarative list configuration.
    """
    def __init__(
        self,
        permission_tag: str,
        query_builder: Callable[[Session, AffiliationContext], Select],
        search_fields: List[Any],
        sort_fields: Dict[str, Any],
        filter_fields: Optional[Dict[str, Any]] = None,
        *,
        cache_enabled: bool = True,
        cache_ttl: int = 300,
        cache_scope: CacheScope = CacheScope.BRANCH,

    ):
        if not permission_tag or not callable(query_builder):
            raise TypeError("permission_tag and query_builder are required.")

        # --- normalize cache_scope so strings ("COMPANY"/"BRANCH"/"GLOBAL") are accepted ---
        original = cache_scope
        if not isinstance(cache_scope, CacheScope):
            if isinstance(cache_scope, str):
                # try Enum by NAME ("COMPANY"), then by VALUE ("company")
                try:
                    cache_scope = CacheScope[cache_scope.upper()]
                except KeyError:
                    cache_scope = CacheScope(cache_scope.lower())
            else:
                cache_scope = CacheScope.BRANCH
        if original != cache_scope:
            log.info("[lists] Normalized cache_scope %r -> %r", original, cache_scope)

        self.permission_tag = permission_tag
        self.query_builder = query_builder
        self.search_fields = search_fields or []
        self.sort_fields = sort_fields or {}
        self.filter_fields = filter_fields or {}
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.cache_scope = cache_scope

LIST_REGISTRY: Dict[str, Dict[str, ListConfig]] = {}

def register_list_configs(module_name: str, configs: Dict[str, ListConfig]) -> None:
    if module_name not in LIST_REGISTRY:
        LIST_REGISTRY[module_name] = {}
    LIST_REGISTRY[module_name].update(configs)
    # log a compact view of registrations
    for key, cfg in configs.items():
        log.info(
            "[lists] Registered config module=%s entity=%s scope=%s ttl=%s cached=%s",
            module_name, key, getattr(cfg.cache_scope, "value", cfg.cache_scope),
            cfg.cache_ttl, cfg.cache_enabled
        )

def get_list_config(module_name: str, entity_name: str) -> ListConfig:
    module = LIST_REGISTRY.get(module_name)
    if not module:
        raise ValueError(f"Module '{module_name}' not found or has no registered lists.")
    cfg = module.get(entity_name)
    if not cfg:
        raise ValueError(f"List config for '{entity_name}' in module '{module_name}' not found.")
    return cfg


# --- Detail Config (The Refined Hybrid) ---
class DetailConfig:
    """
    Declarative configuration for fetching a single document.

    - loader(session, ctx, id) -> dict | None
    - resolver_map: optional { "by_key": resolver(session, ctx, identifier_str) -> int | None }
      Use for lookups by name/code; security allowed to short-circuit early.
    - identifier_field: alternative to resolver_map for simple 'id' lookups.
    - cache_enabled: False by default; turn on for mostly-static doctypes (e.g., Items).
    """
    def __init__(
        self,
        *,
        permission_tag: str,
        loader: Callable[[Session, AffiliationContext, int], Optional[Dict[str, Any]]],
        resolver_map: Optional[Dict[str, Callable[[Session, AffiliationContext, str], Optional[int]]]] = None,
        identifier_field: Optional[Column] = None,
        cache_enabled: bool = False,
        cache_ttl: int = 300,
        default_by: Optional[str] = None,
    ):
        if not all([permission_tag, callable(loader)]):
            raise TypeError("permission_tag and loader are required.")
        if not resolver_map and identifier_field is None:
            raise TypeError("Provide either a resolver_map or an identifier_field.")
        if resolver_map and identifier_field is not None:
            raise TypeError("Provide either resolver_map OR identifier_field, not both.")
        # validate default_by if provided
        if default_by and resolver_map and default_by not in resolver_map:
            raise TypeError(f"default_by='{default_by}' not in resolver_map keys: {list(resolver_map.keys())}")

        self.permission_tag = permission_tag
        self.loader = loader
        self.resolver_map = resolver_map or {}
        self.identifier_field = identifier_field
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.default_by = default_by

DETAIL_REGISTRY: Dict[str, Dict[str, DetailConfig]] = {}

def register_detail_configs(module_name: str, configs: Dict[str, DetailConfig]) -> None:
    if module_name not in DETAIL_REGISTRY:
        DETAIL_REGISTRY[module_name] = {}
    DETAIL_REGISTRY[module_name].update(configs)
    for key, cfg in configs.items():
        log.info("[detail] Registered module=%s entity=%s cached=%s ttl=%ss",
                 module_name, key, cfg.cache_enabled, cfg.cache_ttl)

def get_detail_config(module_name: str, entity_name: str) -> DetailConfig:
    module = DETAIL_REGISTRY.get(module_name)
    if not module:
        raise ValueError(f"Module '{module_name}' not found or has no registered detail views.")
    cfg = module.get(entity_name)
    if not cfg:
        raise ValueError(f"Detail config for '{entity_name}' in module '{module_name}' not found.")
    return cfg