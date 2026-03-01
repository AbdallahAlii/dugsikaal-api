# app/common/cache/keys.py
from __future__ import annotations
import json, hashlib
from typing import Any, Mapping, Optional

def _hash_params(params: Mapping[str, Any]) -> str:
    s = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def epoch_key() -> str:
    return "v:epoch:global"

def v_detail(entity: str, record_id: Any) -> str:
    return f"v:detail:{entity}:{record_id}"

def v_list(entity_scope: str) -> str:
    return f"v:list:{entity_scope}"

def v_user_profile(user_id: int) -> str:
    return f"v:user_profile:{user_id}"

def k_detail(entity: str, record_id: Any, *, epoch: int, version: int) -> str:
    return f"docdetail:{entity}:e{epoch}:v{version}:{record_id}"

def k_list(entity_scope: str, *, epoch: int, version: int, params: Mapping[str, Any]) -> str:
    return f"doclist:{entity_scope}:e{epoch}:v{version}:{_hash_params(params)}"

def k_user_profile(user_id: int, *, epoch: int, version: int) -> str:
    return f"user_profile:e{epoch}:v{version}:{user_id}"