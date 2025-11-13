# application_data_import/services/preview_service.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple

from .policy_service import get_policy


def preflight(reference_doctype: str, rows: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """
    Returns (warnings, infos). Keep it lightweight; deep rules live in domain services.
    """
    policy = get_policy(reference_doctype)
    warnings: List[str] = []
    infos: List[str] = []
    # Example: remind about computed fields
    if policy.computed_fields:
        warnings.append(f"Computed fields will be ignored on insert: {', '.join(sorted(policy.computed_fields))}")
    return warnings, infos
