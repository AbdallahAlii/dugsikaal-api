# app/application_print/registry/print_registry.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext

log = logging.getLogger(__name__)


@dataclass
class PrintConfig:
    """
    Configuration for a printable resource in a module.

    - module_name:   high-level module (accounting, hr, stock, ...)
    - entity_name:   logical entity within that module (payments, sales_invoices, ...)
    - permission_tag: RBAC resource (e.g. "PaymentEntry", "SalesInvoice").
    - doctype:      logical doctype string, used to find PrintFormat rows.
    - loader:       (session, ctx, identifier) -> dict | None
                    identifier can be a code or id (your loader decides).
    """
    permission_tag: str
    doctype: str
    loader: Callable[[Session, AffiliationContext, str], dict | None]


# module_name -> entity_name -> PrintConfig
PRINT_REGISTRY: Dict[str, Dict[str, PrintConfig]] = {}


def register_print_configs(module_name: str, configs: Dict[str, PrintConfig]) -> None:
    """
    Called from each module (accounting, hr, inventory...) to register
    its printable doctypes.
    """
    if module_name not in PRINT_REGISTRY:
        PRINT_REGISTRY[module_name] = {}
    PRINT_REGISTRY[module_name].update(configs)

    for entity, cfg in configs.items():
        log.info(
            "[print] Registered print config module=%s entity=%s doctype=%s perm=%s",
            module_name, entity, cfg.doctype, cfg.permission_tag
        )


def get_print_config(module_name: str, entity_name: str) -> PrintConfig:
    module = PRINT_REGISTRY.get(module_name)
    if not module:
        raise ValueError(f"Print module '{module_name}' not found or has no registered prints.")
    cfg = module.get(entity_name)
    if not cfg:
        raise ValueError(f"Print config for '{entity_name}' in module '{module_name}' not found.")
    return cfg
