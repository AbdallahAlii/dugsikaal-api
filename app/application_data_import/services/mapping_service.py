
# application_data_import/services/mapping_service.py
from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional

from sqlalchemy import select
from config.database import db

from ..registry.field_resolver import resolve_headers_to_fields
from ..registry.doctype_meta import get_model_meta
from ..services.policy_service import get_policy


def _bulk_fetch_name_to_id(
    table_path: str,
    name_col: str,
    id_col: str,
    company_id: Optional[int],
) -> Dict[str, int]:
    """
    Load mapping name(lower) -> id for a link table within company scope if present.
    """
    mod_path, model_name = table_path.split(":")
    import importlib
    mod = importlib.import_module(mod_path)
    model = getattr(mod, model_name)

    q = select(
        getattr(model, id_col).label("id"),
        getattr(model, name_col).label("name"),
    )
    if hasattr(model, "company_id") and company_id:
        q = q.where(getattr(model, "company_id") == company_id)

    rows = db.session.execute(q).mappings().all()
    return {
        str(r["name"]).strip().lower(): int(r["id"])
        for r in rows
        if r["name"] is not None
    }


def build_header_map(
    reference_doctype: str,
    incoming_headers: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Returns (final_columns, unknown_headers)

    - Users may upload headers as labels or fieldnames.
    - We preserve the original order but emit backend fieldnames only.
    - Unknown headers are returned so the preview can warn.

    IMPORTANT:
    - For doctypes like StockReconciliation we also allow fields that are
      NOT real columns on the header model (e.g. item_id, warehouse_id,
      quantity, valuation_rate) as long as they are listed in
      template.always_include.
    """
    policy = get_policy(reference_doctype)
    meta = get_model_meta(policy.cfg["model"])

    # All real model fields for this DocType
    all_fields = {f["fieldname"] for f in meta["fields"]}

    # Template-defined important columns (can include non-model fields)
    tmpl = policy.cfg.get("template") or {}
    always_include = set(tmpl.get("always_include", []) or [])

    # Fields we are allowed to keep
    allowed_fields = all_fields | always_include

    # Resolve headers -> backend fieldnames (using labels + fieldnames)
    header_to_field, unknown = resolve_headers_to_fields(
        reference_doctype,
        incoming_headers,
    )

    # Keep the order of incoming headers; include only allowed fields
    ordered_fields: List[str] = []
    seen = set()

    for hdr in incoming_headers:
        fname = header_to_field.get(hdr)
        if fname and (fname in allowed_fields) and fname not in seen:
            ordered_fields.append(fname)
            seen.add(fname)

    return ordered_fields, unknown


def resolve_links_bulk(
    reference_doctype: str,
    rows: List[Dict[str, Any]],
    company_id: Optional[int],
) -> Tuple[List[Dict[str, Any]], List[Tuple[int, str]]]:
    """
    Applies registry resolvers to transform user-provided names into *_id integers.
    Returns (new_rows, errors[(row_index, message), ...])
    """
    policy = get_policy(reference_doctype)
    resolvers = policy.resolvers

    from collections import defaultdict
    needed: Dict[str, set] = defaultdict(set)

    # Collect distinct lookups per resolver key
    for _, r in enumerate(rows):
        for field, spec in resolvers.items():
            # We only handle simple scalar fields here
            if "[]" in field:
                continue
            if r.get(field) not in (None, ""):
                needed[field].add(str(r[field]).strip().lower())

    # Bulk prefetch per resolver
    maps: Dict[str, Dict[str, int]] = {}

    for field, spec in resolvers.items():
        if "[]" in field:
            continue

        src = spec.get("source")  # e.g. "ItemGroup", "Item", "Warehouse", "Account"

        # Explicit mapping to model paths (extend as you add sources)
        model_path_map = {
            "ItemGroup": "app.application_nventory.inventory_models:ItemGroup",
            "UnitOfMeasure": "app.application_nventory.inventory_models:UnitOfMeasure",
            "Brand": "app.application_nventory.inventory_models:Brand",
            "Branch": "app.application_org.models.company:Branch",
            # NEW for Stock Reconciliation
            "Item": "app.application_nventory.inventory_models:Item",
            "Warehouse": "app.application_stock.stock_models:Warehouse",
            "Account": "app.application_accounting.chart_of_accounts.models:Account",
        }

        model_path = model_path_map.get(src)
        if not model_path:
            continue

        maps[field] = _bulk_fetch_name_to_id(
            model_path,
            name_col="name",
            id_col="id",
            company_id=company_id,
        )

    # Apply conversions
    errors: List[Tuple[int, str]] = []
    out_rows: List[Dict[str, Any]] = []

    for i, r in enumerate(rows):
        newr = dict(r)
        for field, m in maps.items():
            raw = r.get(field)
            if raw in (None, ""):
                continue
            key = str(raw).strip().lower()
            id_ = m.get(key)
            if id_ is None:
                spec = resolvers.get(field, {})
                if not spec.get("optional"):
                    errors.append((i, f"Unknown {field}='{raw}'"))
                newr[field] = None
            else:
                newr[field] = id_
        out_rows.append(newr)

    return out_rows, errors
