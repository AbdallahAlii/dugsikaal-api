# application_data_import/registry/doctype_meta.py
from __future__ import annotations
import importlib
from typing import Any, Dict, List, Optional

from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.orm import DeclarativeMeta


# Basic map for label defaults. In real projects you might store nicer labels in a separate dict.
def _default_label(field_name: str) -> str:
    return field_name.replace("_", " ").title()


def _enum_options(col_type: TypeEngine | Any) -> Optional[List[str]]:
    try:
        enum_cls = getattr(col_type, "enum_class", None)
        if not enum_cls:
            return None
        return [getattr(m, "value", m.name) for m in enum_cls]  # values as strings
    except Exception:
        return None


def get_model_meta(model_path: str) -> Dict[str, Any]:
    """
    Resolve "pkg.mod:Model" and introspect SQLAlchemy columns.
    Returns {
      "table": "...",
      "fields": [{ "fieldname": str, "type": str, "required": bool, "label": str, "enum_options": [...] }, ...]
    }
    """
    mod_path, model_name = model_path.split(":")
    mod = importlib.import_module(mod_path)
    model: DeclarativeMeta = getattr(mod, model_name)

    fields = []
    for col in model.__table__.columns:
        fname = col.name
        typ = type(getattr(col, "type", None)).__name__
        label = _default_label(fname)
        required = not getattr(col, "nullable", True) and (fname not in ("id",))
        enum_opts = _enum_options(getattr(col, "type", None))

        fields.append({
            "fieldname": fname,
            "type": typ,
            "required": bool(required),
            "label": label,
            "enum_options": enum_opts,
        })

    return {
        "table": model.__table__.fullname,
        "fields": fields,
    }
