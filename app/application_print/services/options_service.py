# app/application_print/services/options_service.py
from __future__ import annotations

from typing import Dict, List
from app.application_print.registry.print_registry import PRINT_REGISTRY, PrintConfig


class PrintOptionsService:
    def list_modules(self) -> List[str]:
        return sorted(PRINT_REGISTRY.keys())

    def list_entities_for_module(self, module: str) -> Dict[str, PrintConfig]:
        return PRINT_REGISTRY.get(module, {})

    def list_all(self) -> Dict[str, Dict[str, PrintConfig]]:
        return PRINT_REGISTRY


print_options_service = PrintOptionsService()
