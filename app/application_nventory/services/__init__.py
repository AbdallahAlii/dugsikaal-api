# app/application_nventory/services/__init__.py
from __future__ import annotations

"""
Service package for Inventory.

We re-export the main InventoryService and the Data Import adapters so that
paths like 'app.application_nventory.services.create_item_via_import'
work correctly.
"""

from app.application_nventory.inventory_services import InventoryService
from .adapters import (
    create_item_via_import,
    update_item_by_id,
    update_item_by_sku,
)

__all__ = [
    "InventoryService",
    "create_item_via_import",
    "update_item_by_id",
    "update_item_by_sku",
]
