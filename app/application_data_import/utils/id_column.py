# application_data_import/utils/id_column.py
from __future__ import annotations
from ..services.policy_service import get_policy


def pick_identity(reference_doctype: str) -> str:
    return get_policy(reference_doctype).identity_for_update
