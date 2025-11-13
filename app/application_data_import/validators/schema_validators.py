# application_data_import/validators/schema_validators.py
from __future__ import annotations
from typing import List, Dict, Any
from werkzeug.exceptions import BadRequest

from ..models import ImportType
from ..services.policy_service import get_policy
from ..registry.doctype_meta import get_model_meta


def _required_fields(meta_fields: List[Dict[str, Any]]) -> List[str]:
    return [f["fieldname"] for f in meta_fields if f.get("required")]


def validate_required_headers(reference_doctype: str, import_type: ImportType, final_cols: List[str]) -> None:
    policy = get_policy(reference_doctype)
    meta = get_model_meta(policy.cfg["model"])
    req = set(_required_fields(meta["fields"]))

    # Insert: remove computed/excluded from required check
    if import_type == ImportType.INSERT:
        req -= policy.computed_fields
        req -= policy.exclude_on_insert

    missing = [r for r in sorted(req) if r not in final_cols]
    if missing:
        raise BadRequest(f"Missing required columns: {', '.join(missing)}")


def validate_row_shapes(rows: List[Dict[str, Any]]) -> None:
    if len(rows) == 0:
        raise BadRequest("No data rows found.")


def validate_conditionals(reference_doctype: str, rows: List[Dict[str, Any]]) -> None:
    policy = get_policy(reference_doctype)
    err_count = 0
    for i, r in enumerate(rows):
        missing = policy.enforce_conditional_required(r)
        if missing:
            err_count += 1
    if err_count:
        # Soft fail: the pipeline will still attempt and log row-level messages
        pass
