# application_data_import/services/policy_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set

from werkzeug.exceptions import BadRequest

from ..registry.doctype_registry import get_doctype_cfg
from ..registry.doctype_meta import get_model_meta


class Policy:
    def __init__(self, cfg: Dict[str, Any], meta: Dict[str, Any]):
        self.cfg = cfg
        self.meta = meta

    @property
    def identity_for_update(self) -> str:
        return (self.cfg.get("identity", {}) or {}).get("for_update", "id")

    @property
    def exclude_on_insert(self) -> Set[str]:
        return set((self.cfg.get("template", {}) or {}).get("exclude_fields_on_insert", []) or [])

    @property
    def computed_fields(self) -> Set[str]:
        return set((self.cfg.get("template", {}) or {}).get("computed_fields", []) or [])

    @property
    def label_aliases(self) -> Dict[str, str]:
        return (self.cfg.get("template", {}) or {}).get("labels", {}) or {}

    @property
    def resolvers(self) -> Dict[str, Any]:
        return self.cfg.get("resolvers", {}) or {}

    @property
    def conditional_required(self) -> List[Dict[str, Any]]:
        return self.cfg.get("conditional_required", []) or []

    def enforce_conditional_required(self, row: Dict[str, Any]) -> List[str]:
        """Returns list of missing fields for the row."""
        missing: List[str] = []
        for rule in self.conditional_required:
            when = rule.get("when", {})
            require = rule.get("require", [])
            ok = True
            for k, v in (when or {}).items():
                if str(row.get(k, "")).strip() != str(v):
                    ok = False
                    break
            if ok:
                for r in (require or []):
                    if row.get(r) in (None, "", []):
                        missing.append(r)
        return missing


def get_policy(reference_doctype: str) -> Policy:
    cfg = get_doctype_cfg(reference_doctype)
    meta = get_model_meta(cfg["model"])
    return Policy(cfg, meta)
