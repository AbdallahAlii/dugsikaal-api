from __future__ import annotations

from app.application_doctypes.core_lists.config import DetailConfig, register_detail_configs
from app.application_rbac.query_builders.detail_builders import (
    resolve_id_strict, resolve_user_by_username, load_user_detail
)

RBAC_DETAIL_CONFIGS = {
    "users": DetailConfig(
        permission_tag="User",
        loader=load_user_detail,
        resolver_map={
            "id": resolve_id_strict,
            "username": resolve_user_by_username,
            "name": resolve_user_by_username,  # alias if you like
        },
        cache_enabled=False,     # user details change often
        cache_ttl=300,
        default_by="username",
    ),
}

def register_rbac_detail_configs() -> None:
    register_detail_configs("rbac", RBAC_DETAIL_CONFIGS)
