# # application_data_import/validators/schema_validators.py
# from __future__ import annotations
# from typing import List, Dict, Any
# from werkzeug.exceptions import BadRequest
#
# from ..models import ImportType
# from ..services.policy_service import get_policy
# from ..registry.doctype_meta import get_model_meta
#
# # System/audit fields that should never be required from import files
# _AUDIT_FIELDS = {
#     "created_at",
#     "updated_at",
#     "deleted_at",
#     # add more here if you use other audit columns globally
#     # e.g. "created_on", "updated_on"
# }
#
#
# def _required_fields(meta_fields: List[Dict[str, Any]]) -> List[str]:
#     """
#     Take SQLAlchemy meta fields and return which should be treated as
#     "required" for import header validation.
#
#     We EXCLUDE audit/system fields like created_at/updated_at – these are
#     set by the DB / ORM and should not be forced in the spreadsheet.
#     """
#     out: List[str] = []
#     for f in meta_fields:
#         fname = f.get("fieldname")
#         if not fname:
#             continue
#         if not f.get("required"):
#             continue
#         # Never require audit fields in imports
#         if fname in _AUDIT_FIELDS:
#             continue
#         out.append(fname)
#     return out
#
#
# def validate_required_headers(
#     reference_doctype: str,
#     import_type: ImportType,
#     final_cols: List[str],
# ) -> None:
#     """
#     Ensure that all truly-required fields (business fields) are present
#     in the final column list we will use in the pipeline.
#
#     - Required fields come from SQLAlchemy meta (non-nullable columns)
#     - We drop system/audit fields (created_at, updated_at, etc.)
#     - For INSERT, we also drop computed/excluded fields from the policy.
#     """
#     policy = get_policy(reference_doctype)
#     meta = get_model_meta(policy.cfg["model"])
#
#     # Required from model meta (minus system/audit)
#     req = set(_required_fields(meta["fields"]))
#
#     # INSERT: remove computed/excluded from required check
#     if import_type == ImportType.INSERT:
#         req -= policy.computed_fields
#         req -= policy.exclude_on_insert
#
#     # Now compute which required fields are missing from the incoming file
#     missing = [r for r in sorted(req) if r not in final_cols]
#     if missing:
#         raise BadRequest(f"Missing required columns: {', '.join(missing)}")
#
#
# def validate_row_shapes(rows: List[Dict[str, Any]]) -> None:
#     """
#     Basic sanity check: we must have at least one data row.
#     """
#     if len(rows) == 0:
#         raise BadRequest("No data rows found.")
#
#
# def validate_conditionals(reference_doctype: str, rows: List[Dict[str, Any]]) -> None:
#     """
#     Enforce conditional required rules from policy, but as a
#     *soft* validation: errors are recorded per-row in logs later.
#     """
#     policy = get_policy(reference_doctype)
#     err_count = 0
#     for i, r in enumerate(rows):
#         missing = policy.enforce_conditional_required(r)
#         if missing:
#             err_count += 1
#     if err_count:
#         # Soft fail: the pipeline will still attempt and log row-level messages
#         # via DataImportLog inside the main pipeline.
#         pass
# application_data_import/validators/schema_validators.py
from __future__ import annotations
from typing import List, Dict, Any
from werkzeug.exceptions import BadRequest

from ..models import ImportType
from ..services.policy_service import get_policy
from ..registry.doctype_meta import get_model_meta

# System/audit fields that should never be required from import files
_AUDIT_FIELDS = {
    "created_at",
    "updated_at",
    "deleted_at",
    # add more here if you use other audit columns globally
    # e.g. "created_on", "updated_on"
}


def _required_fields(meta_fields: List[Dict[str, Any]]) -> List[str]:
    """
    Take SQLAlchemy meta fields and return which should be treated as
    "required" for import header validation.

    We EXCLUDE audit/system fields like created_at/updated_at – these are
    set by the DB / ORM and should not be forced in the spreadsheet.
    """
    out: List[str] = []
    for f in meta_fields:
        fname = f.get("fieldname")
        if not fname:
            continue
        if not f.get("required"):
            continue
        # Never require audit fields in imports
        if fname in _AUDIT_FIELDS:
            continue
        out.append(fname)
    return out


def validate_required_headers(
    reference_doctype: str,
    import_type: ImportType,
    final_cols: List[str],
) -> None:
    """
    Ensure that all truly-required fields (business fields) are present
    in the final column list we will use in the pipeline.

    Required set is built from:
    - SQLAlchemy meta-required fields (non-nullable, minus audit/system and computed/excluded)
    - PLUS registry.template["always_include"] for INSERT imports.

    This gives you a clear, per-DocType definition of which columns
    MUST exist in the Excel file for imports to be valid.
    """
    policy = get_policy(reference_doctype)
    meta = get_model_meta(policy.cfg["model"])

    # Required from model meta (minus system/audit)
    meta_required = set(_required_fields(meta["fields"]))

    # INSERT: remove computed/excluded from required check
    if import_type == ImportType.INSERT:
        meta_required -= policy.computed_fields
        meta_required -= policy.exclude_on_insert

    # Registry template "always_include" (per-doctype important columns)
    tmpl = (policy.cfg.get("template") or {})
    always_include = set(tmpl.get("always_include", []) or [])

    if import_type == ImportType.INSERT:
        # INSERT: both model-required and always_include are required
        req = meta_required | always_include
    else:
        # UPDATE: only model-required; user might only update some fields.
        req = meta_required

    # Now compute which required fields are missing from the incoming file
    missing = [r for r in sorted(req) if r not in final_cols]
    if missing:
        raise BadRequest(f"Missing required columns: {', '.join(missing)}")


def validate_row_shapes(rows: List[Dict[str, Any]]) -> None:
    """
    Basic sanity check: we must have at least one data row.
    """
    if len(rows) == 0:
        raise BadRequest("No data rows found.")


def validate_conditionals(reference_doctype: str, rows: List[Dict[str, Any]]) -> None:
    """
    Enforce conditional required rules from policy, but as a
    *soft* validation: errors are recorded per-row in logs later.
    """
    policy = get_policy(reference_doctype)
    err_count = 0
    for i, r in enumerate(rows):
        missing = policy.enforce_conditional_required(r)
        if missing:
            err_count += 1
    if err_count:
        # Soft fail: the pipeline will still attempt and log row-level messages
        # via DataImportLog inside the main pipeline.
        pass
