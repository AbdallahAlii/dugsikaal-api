from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_parties.query_builders.party_detail_builders import (
    resolve_id_strict,
    resolve_customer_by_code,
    resolve_supplier_by_code,
    load_customer_detail,
    load_supplier_detail,
)

PARTIES_DETAIL_CONFIGS = {
    "customers": DetailConfig(
        permission_tag="Party",       # or "Customer" if you split perms
        loader=load_customer_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_customer_by_code,
        },
        cache_enabled=True,
        cache_ttl=900,                # 15 minutes; adjust as you like
        default_by="code",
    ),
    "suppliers": DetailConfig(
        permission_tag="Party",
        loader=load_supplier_detail,
        resolver_map={
            "id": resolve_id_strict,
            "code": resolve_supplier_by_code,
        },
        cache_enabled=True,
        cache_ttl=900,
        default_by="code",
    ),
}

def register_parties_detail_configs() -> None:
    register_detail_configs("parties", PARTIES_DETAIL_CONFIGS)
