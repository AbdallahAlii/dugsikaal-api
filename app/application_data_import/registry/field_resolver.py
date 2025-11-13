# application_data_import/registry/field_resolver.py
from __future__ import annotations
from typing import Dict, List, Tuple

from .doctype_registry import get_doctype_cfg
from .doctype_meta import get_model_meta


def _normalize(s: str) -> str:
    return (s or "").strip().casefold()


# --- Public helper to keep other modules stable (compat) ---
def normalize_header(s: str) -> str:
    """Compatibility helper; same behavior as internal _normalize."""
    return _normalize(s)


def _build_alias_map(reference_doctype: str) -> Dict[str, str]:
    """
    Build label/alias → fieldname map for a DocType from:
      1) Registry template.labels
      2) SQLAlchemy model metadata labels (if present)
      3) Identity field (for update) as a last resort
    """
    cfg = get_doctype_cfg(reference_doctype)
    meta = get_model_meta(cfg["model"])

    alias_map: Dict[str, str] = {}

    # 1) explicit labels in registry
    labels_cfg = (cfg.get("template", {}) or {}).get("labels", {}) or {}
    for fieldname, label in labels_cfg.items():
        alias_map[_normalize(label)] = fieldname

    # 2) model meta labels
    for f in meta["fields"]:
        label = (f.get("label") or "").strip()
        fieldname = f["fieldname"]
        if label:
            alias_map.setdefault(_normalize(label), fieldname)

    # 3) identity field itself
    identity = (cfg.get("identity") or {}).get("for_update")
    if identity:
        alias_map.setdefault(_normalize(identity), identity)

    return alias_map


def resolve_headers_to_fields(
    reference_doctype: str,
    incoming_headers: List[str]
) -> Tuple[Dict[str, str], List[str]]:
    """
    Map user headers (labels or fieldnames) → real fieldnames.
    Returns (header_to_field, unknown_headers).

    Example:
      headers = ["Item Name", "Item Type", "Item Group", "UOM", "Brand"]
      -> {"Item Name": "name", "Item Type": "item_type", ...}, []
    """
    cfg = get_doctype_cfg(reference_doctype)
    meta = get_model_meta(cfg["model"])

    fieldnames = {f["fieldname"] for f in meta["fields"]}
    fieldnames_norm = {_normalize(fn): fn for fn in fieldnames}
    alias_map = _build_alias_map(reference_doctype)

    header_to_field: Dict[str, str] = {}
    unknown: List[str] = []

    for hdr in incoming_headers:
        key = _normalize(hdr)
        # direct fieldname support
        if key in fieldnames_norm:
            header_to_field[hdr] = fieldnames_norm[key]
            continue
        # label/alias support
        if key in alias_map:
            header_to_field[hdr] = alias_map[key]
            continue
        unknown.append(hdr)

    return header_to_field, unknown


# ---- Compatibility wrapper so older imports won't crash ----
def resolve_headers(
    incoming_headers: List[str],
    labels_map: Dict[str, str] | None = None  # kept for signature compatibility; ignored
) -> Tuple[Dict[int, str], List[str]]:
    """
    Return (idx_to_fieldname, unknown_headers) to mimic older callers.
    """
    # We can't know the doctype here, so this wrapper is only useful if callers
    # immediately post-process with real doctype context. Most code has been moved
    # to resolve_headers_to_fields(doctypename, headers). Keep this as a minimal shim.
    idx_to_field: Dict[int, str] = {}
    unknown: List[str] = []
    # Without doctype we can't map labels; best-effort: assume headers are fieldnames
    for i, hdr in enumerate(incoming_headers):
        key = _normalize(hdr)
        if key:  # accept as-is
            idx_to_field[i] = hdr
        else:
            unknown.append(hdr)
    return idx_to_field, unknown
