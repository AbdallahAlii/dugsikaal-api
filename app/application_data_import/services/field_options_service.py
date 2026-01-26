# application_data_import/services/field_options_service.py
from __future__ import annotations
from typing import List, Dict, Any, Optional

from config.database import db
from ..models import DataImport, ImportType, DataImportTemplateField
from ..registry.doctype_registry import get_doctype_cfg
from ..registry.doctype_meta import get_model_meta
from ..services.policy_service import get_policy


def get_template_field_options(data_import_id: int) -> Dict[str, Any]:
    """
    Return all possible fields for the given DataImport, plus which ones
    are selected / required. This powers the 'Select Fields to Insert' UI.

    Output example:
    {
      "reference_doctype": "Item",
      "import_type": "Insert",
      "fields": [
        {
          "field_name": "name",
          "label": "Item Name",
          "required": true,
          "selected": true,
          "is_always": true,
          "column_index": 0
        },
        ...
      ]
    }
    """
    di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
    if not di:
        raise LookupError("Data Import not found.")

    reference_doctype = di.reference_doctype
    import_type = di.import_type

    cfg = get_doctype_cfg(reference_doctype)
    policy = get_policy(reference_doctype)
    meta = get_model_meta(cfg["model"])

    tmpl_cfg = (cfg.get("template") or {})
    labels_cfg = tmpl_cfg.get("labels", {}) or {}
    always_include = tmpl_cfg.get("always_include", []) or []

    # Fields that should never be user-filled in INSERT mode
    excluded = set(policy.exclude_on_insert)
    if import_type == ImportType.INSERT:
        excluded |= set(policy.computed_fields)

    # existing selection, if user already saved fields
    existing_rows = (
        db.session.query(DataImportTemplateField)
        .filter(DataImportTemplateField.data_import_id == data_import_id)
        .all()
    )
    existing_by_field = {r.field_name: r for r in existing_rows}

    results: List[Dict[str, Any]] = []

    for f in meta["fields"]:
        fname = f["fieldname"]

        # skip tech/internal columns
        if fname in excluded:
            continue
        if fname in ("id", "company_id", "branch_id", "created_by_id",
                     "created_at", "updated_at"):
            continue

        # basic label: registry label > meta label > fieldname
        label = labels_cfg.get(fname) or (f.get("label") or fname.replace("_", " ").title())

        # required based on meta + import policy
        # (you can extend this using policy.conditional_required if you want)
        required = bool(f.get("required", False))

        existing = existing_by_field.get(fname)
        selected = False
        column_index = None

        if existing_rows:
            # if user has saved selection → follow that
            if existing:
                selected = True
                column_index = existing.column_index
        else:
            # first time: default select "always_include" + required
            selected = (fname in always_include) or required

        results.append(
            {
                "field_name": fname,
                "label": label,
                "required": required,
                "selected": selected,
                "is_always": fname in always_include,
                "column_index": column_index,
            }
        )

    # simple sort: required + always first, then by label
    results.sort(
        key=lambda r: (
            0 if r["required"] else 1,
            0 if r["is_always"] else 1,
            (r["column_index"] if r["column_index"] is not None else 9999),
            r["label"].lower(),
        )
    )

    return {
        "reference_doctype": reference_doctype,
        "import_type": import_type.value,
        "fields": results,
    }
