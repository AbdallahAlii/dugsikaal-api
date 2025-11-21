# application_data_import/services/template_service.py
from __future__ import annotations
import csv
import io
from typing import List, Tuple, Optional, Dict

from sqlalchemy import select
from config.database import db

from ..models import FileType, DataImport, DataImportTemplateField
from ..registry.doctype_registry import get_doctype_cfg
from ..registry.doctype_meta import get_model_meta
from ..services.policy_service import get_policy

def _labels_for_download(di: DataImport) -> List[str]:
    """
    If user saved template_fields for this import, use those labels in order.
    Otherwise, derive a default set from registry (always_include + reasonable defaults).
    """
    rows = sorted(di.template_fields, key=lambda r: r.column_index)
    if rows:
        return [r.field_label for r in rows]

    # no saved rows -> build a sensible default from registry
    cfg = get_doctype_cfg(di.reference_doctype)
    labels_cfg = (cfg.get("template") or {}).get("labels") or {}
    always = (cfg.get("template") or {}).get("always_include") or []

    # Start from always_include, then others (not excluded/computed)
    exclude = set((cfg.get("template") or {}).get("exclude_fields_on_insert") or [])
    computed = set((cfg.get("template") or {}).get("computed_fields") or [])
    allowed_fields = []
    for fname in always:
        if fname not in exclude and fname not in computed:
            lbl = labels_cfg.get(fname, fname)
            allowed_fields.append(lbl)

    # You can add more defaults here if you want beyond always_include
    return allowed_fields
def _choose_columns_from_meta(reference_doctype: str, selected_fields: Optional[List[str]]) -> List[str]:
    policy = get_policy(reference_doctype)
    meta = get_model_meta(get_doctype_cfg(reference_doctype)["model"])

    all_fields = [f["fieldname"] for f in meta["fields"]]
    selected = selected_fields or []
    always = (policy.cfg.get("template", {}) or {}).get("always_include", []) or []
    excluded = policy.exclude_on_insert.union(policy.computed_fields)

    cols: List[str] = []
    seen = set()
    for name in always + selected + all_fields:
        if name in excluded:
            continue
        if name not in all_fields:
            continue
        if name in seen:
            continue
        cols.append(name)
        seen.add(name)
    return cols


def _choose_columns_from_import_id(data_import_id: int) -> List[str]:
    di: DataImport | None = db.session.get(DataImport, data_import_id)
    if not di:
        return []
    reference_doctype = di.reference_doctype
    policy = get_policy(reference_doctype)
    meta = get_model_meta(get_doctype_cfg(reference_doctype)["model"])
    all_fields = {f["fieldname"] for f in meta["fields"]}

    # Pull persisted template fields in saved order:
    rows = (
        db.session.query(DataImportTemplateField)
        .filter(DataImportTemplateField.data_import_id == data_import_id)
        .order_by(DataImportTemplateField.column_index.asc())
        .all()
    )
    desired = [r.field_name for r in rows if r.field_name in all_fields]

    # Auto-include "always_include", auto-exclude computed/excluded on INSERT
    always = (policy.cfg.get("template", {}) or {}).get("always_include", []) or []
    excluded = policy.exclude_on_insert.union(policy.computed_fields)

    cols: List[str] = []
    seen = set()
    for name in always + desired:
        if di.import_type.name == "INSERT" and name in excluded:
            continue
        if name not in all_fields:
            continue
        if name in seen:
            continue
        cols.append(name)
        seen.add(name)
    return cols


def _fetch_sample_rows(reference_doctype: str, columns: List[str], limit: int = 5) -> List[dict]:
    cfg = get_doctype_cfg(reference_doctype)
    mod_path, model_name = cfg["model"].split(":")
    import importlib
    mod = importlib.import_module(mod_path)
    model = getattr(mod, model_name)

    cols = [getattr(model, c) for c in columns if hasattr(model, c)]
    if not cols:
        return []

    q = select(*cols).limit(limit)
    rows = db.session.execute(q).mappings().all()
    return [dict(r) for r in rows]


def _to_csv(columns: List[str], rows: List[dict]) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def _to_xlsx(columns: List[str], rows: List[dict]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c, "") for c in columns])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def build_template_file(
    *,
    reference_doctype: str,
    file_type: FileType,
    export_type: str,          # "blank" | "with_data"
    selected_fields: Optional[List[str]],
    company_id: Optional[int] = None,
    data_import_id: Optional[int] = None,
) -> Tuple[bytes, str, str]:
    """
    If data_import_id is provided, we use saved template fields for that import.
    Otherwise we compute from meta + selected_fields.
    Returns (content, filename, mimetype)
    """
    # ---------- Decide columns (fieldnames) + headers (labels) ----------
    if data_import_id:
        columns = _choose_columns_from_import_id(data_import_id)
        di = db.session.get(DataImport, data_import_id)
        ref = di.reference_doctype if di else reference_doctype

        # Build label map from saved template fields
        label_by_fieldname: Dict[str, str] = {}
        if di:
            tf_rows = sorted(di.template_fields, key=lambda r: r.column_index)
            for r in tf_rows:
                # field_name -> label user picked
                label_by_fieldname[r.field_name] = r.field_label

        cfg = get_doctype_cfg(ref)
        labels_cfg = (cfg.get("template") or {}).get("labels") or {}

        # headers: for each fieldname, pick (saved label) -> cfg label -> fallback fieldname
        headers: List[str] = [
            label_by_fieldname.get(fname) or labels_cfg.get(fname, fname)
            for fname in columns
        ]
    else:
        # No specific DataImport → generic template based on meta + selected_fields
        columns = _choose_columns_from_meta(reference_doctype, selected_fields)
        ref = reference_doctype

        cfg = get_doctype_cfg(ref)
        labels_cfg = (cfg.get("template") or {}).get("labels") or {}
        headers = [labels_cfg.get(fname, fname) for fname in columns]

    # ---------- Build sample rows (optional) ----------
    rows: List[dict] = []
    if export_type.lower() in ("with_data", "with_5_records", "with5"):
        # raw_rows are keyed by fieldnames
        raw_rows = _fetch_sample_rows(ref, columns, limit=5)

        # Convert to label-keyed rows so they match headers
        pairs = list(zip(headers, columns))  # (label, fieldname)
        for r in raw_rows:
            labeled_row = {label: r.get(fieldname, "") for (label, fieldname) in pairs}
            rows.append(labeled_row)

    # ---------- Export as CSV / XLSX ----------
    if file_type == FileType.CSV:
        content = _to_csv(headers, rows)
        return content, f"{ref}_template.csv", "text/csv"
    else:
        content = _to_xlsx(headers, rows)
        return (
            content,
            f"{ref}_template.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
