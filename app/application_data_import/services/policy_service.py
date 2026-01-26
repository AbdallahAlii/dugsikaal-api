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

    # -------------------------------------------------------------------------
    # Core identity / template
    # -------------------------------------------------------------------------
    @property
    def identity_for_update(self) -> str:
        """
        Which field is used as identity when ImportType.UPDATE is selected.
        Defaults to 'id' if not configured.
        """
        return (self.cfg.get("identity", {}) or {}).get("for_update", "id")

    @property
    def exclude_on_insert(self) -> Set[str]:
        """
        Fields that must be forcibly stripped on INSERT imports
        (id, company_id, created_by_id, status, etc.).
        """
        return set(
            (self.cfg.get("template", {}) or {}).get("exclude_fields_on_insert", [])
            or []
        )

    @property
    def computed_fields(self) -> Set[str]:
        """
        Fields that are computed by the server and should be stripped
        from incoming rows on INSERT (like 'sku', 'code', etc.).
        """
        return set(
            (self.cfg.get("template", {}) or {}).get("computed_fields", [])
            or []
        )

    @property
    def label_aliases(self) -> Dict[str, str]:
        """
        Excel header label → fieldname mapping, e.g.
        'Item Code' -> 'sku'
        """
        return (self.cfg.get("template", {}) or {}).get("labels", {}) or {}

    # -------------------------------------------------------------------------
    # Link resolvers / conditional requirements
    # -------------------------------------------------------------------------
    @property
    def resolvers(self) -> Dict[str, Any]:
        """
        Link resolvers used by resolve_links_bulk.
        """
        return self.cfg.get("resolvers", {}) or {}

    @property
    def conditional_required(self) -> List[Dict[str, Any]]:
        """
        Row-level conditional required rules, e.g.
        { when: { item_type: "Stock" }, require: ["base_uom_id"] }
        """
        return self.cfg.get("conditional_required", []) or []

    def enforce_conditional_required(self, row: Dict[str, Any]) -> List[str]:
        """
        Returns list of missing fields for the row based on conditional rules.

        Used by validate_conditionals to build a clean error message.
        """
        missing: List[str] = []
        for rule in self.conditional_required:
            when = rule.get("when", {})
            require = rule.get("require", [])
            ok = True

            # Check if this rule applies to the row
            for k, v in (when or {}).items():
                if str(row.get(k, "")).strip() != str(v):
                    ok = False
                    break

            # If rule applies, ensure all required fields are present
            if ok:
                for r in (require or []):
                    if row.get(r) in (None, "", []):
                        missing.append(r)
        return missing

    # -------------------------------------------------------------------------
    # Import behavior policies (per DocType)
    # -------------------------------------------------------------------------
    @property
    def submit_after_import_allowed(self) -> bool:
        """
        Whether this DocType allows 'submit_after_import' behavior.

        Example:
        - StockReconciliation: True (we may auto-submit after import)
        - Customer, Supplier, Item, Employee: False
        """
        return (self.cfg.get("policies", {}) or {}).get(
            "submit_after_import_allowed", False
        )

    @property
    def mute_emails_supported(self) -> bool:
        """
        Whether this DocType supports the 'mute_emails' flag.
        Mostly informational; runner may also use this if you want to enforce.
        """
        return (self.cfg.get("policies", {}) or {}).get(
            "mute_emails_supported", True
        )


def get_policy(reference_doctype: str) -> Policy:
    """
    Build a Policy wrapper around the registry config + model meta.
    This centralizes all registry-based rules (template, identity, policies).
    """
    cfg = get_doctype_cfg(reference_doctype)
    meta = get_model_meta(cfg["model"])
    return Policy(cfg, meta)
