#
# # app/common/cache/cache_keys.py
# from __future__ import annotations
#
# import json, hashlib
# from typing import Any, Mapping, Optional
#
# def _hash_params(params: Mapping[str, Any]) -> str:
#     s = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
#     return hashlib.sha256(s.encode("utf-8")).hexdigest()
# def global_epoch_key() -> str:
#     return "v:epoch:global"
#
# # ---- Version counters (where we INCR) ----
# def detail_version_key(entity: str, record_id: Any) -> str:
#     return f"v:detail:{entity}:{record_id}"
#
# def list_version_key(entity: str, company_id: Optional[int] = None) -> str:
#     scope = f":company:{company_id}" if company_id is not None else ":global"
#     return f"v:list:{entity}{scope}"
#
# def user_profile_version_key(user_id: int) -> str:
#     return f"v:user_profile:{user_id}"
#
# # ---- Concrete cache keys (include version) ----
# def build_detail_cache_key(entity: str, record_id: Any, version: int) -> str:
#     return f"docdetail:{entity}:v{version}:{record_id}"
#
# def build_list_cache_key(
#     entity: str,
#     version: int,
#     *,
#     company_id: Optional[int] = None,
#     params: Optional[Mapping[str, Any]] = None,
# ) -> str:
#     base = f"doclist:{entity}:v{version}"
#     if company_id is not None:
#         base += f":company:{company_id}"
#     if params:
#         base += f":{_hash_params(params)}"
#     return base
#
# def build_user_profile_cache_key(user_id: int, version: int) -> str:
#     return f"user_profile:v{version}:{user_id}"
#
#
# def build_scoped_user_profile_cache_key(user_id: int, version: int, *, company_id: int | None, branch_id: int | None) -> str:
#     c = company_id or 0
#     b = branch_id or 0
#     # one version counter per user (bump_user_profile invalidates all scopes)
#     return f"user_profile:v{version}:{user_id}:c{c}:b{b}"
#
#
#
# # --- Price List snapshot version & keys --------------------------------------
#
# def price_list_version_key(company_id: int, pl_id: int) -> str:
#     return f"v:plist:{int(company_id)}:{int(pl_id)}"
#
# def price_list_hash_key(company_id: int, pl_id: int, version: int, day_yyyymmdd: str) -> str:
#     return f"plist:c{int(company_id)}:pl{int(pl_id)}:v{int(version)}:d{day_yyyymmdd}"
#
# # ---- UOM cache (per item) (new) ----
# def uom_item_hash_key(item_id: int) -> str:
#     return f"uomconv:item:{int(item_id)}"
#
#
#
#
# # --- COA (Chart of Accounts) version keys ------------------------------------
#
# def coa_balance_version_key(company_id: int) -> str:
#     """
#     Balance version for a company's chart of accounts.
#     Bump this whenever postings affect AccountBalance/current balance.
#     """
#     return f"v:coa:balance:c{int(company_id)}"
from __future__ import annotations

import json, hashlib
from typing import Any, Mapping, Optional

def _hash_params(params: Mapping[str, Any]) -> str:
    s = json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# ✅ Global epoch counter (bump to invalidate EVERYTHING)
def global_epoch_key() -> str:
    return "v:epoch:global"

# ---- Version counters (where we INCR) ----
def detail_version_key(entity: str, record_id: Any) -> str:
    return f"v:detail:{entity}:{record_id}"

def list_version_key(entity: str, company_id: Optional[int] = None) -> str:
    scope = f":company:{company_id}" if company_id is not None else ":global"
    return f"v:list:{entity}{scope}"

def user_profile_version_key(user_id: int) -> str:
    return f"v:user_profile:{user_id}"

# ---- Concrete cache keys (include version + epoch) ----
def build_detail_cache_key(entity: str, record_id: Any, version: int, epoch: int = 1) -> str:
    return f"docdetail:{entity}:e{epoch}:v{version}:{record_id}"

def build_list_cache_key(
    entity: str,
    version: int,
    epoch: int = 1,
    *,
    company_id: Optional[int] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> str:
    base = f"doclist:{entity}:e{epoch}:v{version}"
    if company_id is not None:
        base += f":company:{company_id}"
    if params:
        base += f":{_hash_params(params)}"
    return base

def build_user_profile_cache_key(user_id: int, version: int, epoch: int = 1) -> str:
    return f"user_profile:e{epoch}:v{version}:{user_id}"

def build_scoped_user_profile_cache_key(
    user_id: int,
    version: int,
    epoch: int = 1,
    *,
    company_id: int | None,
    branch_id: int | None,
) -> str:
    c = company_id or 0
    b = branch_id or 0
    return f"user_profile:e{epoch}:v{version}:{user_id}:c{c}:b{b}"

# --- Price List snapshot version & keys --------------------------------------
def price_list_version_key(company_id: int, pl_id: int) -> str:
    return f"v:plist:{int(company_id)}:{int(pl_id)}"

def price_list_hash_key(company_id: int, pl_id: int, version: int, day_yyyymmdd: str) -> str:
    return f"plist:c{int(company_id)}:pl{int(pl_id)}:v{int(version)}:d{day_yyyymmdd}"

# ---- UOM cache (per item) ----
def uom_item_hash_key(item_id: int) -> str:
    return f"uomconv:item:{int(item_id)}"

# --- COA version keys --------------------------------------------------------
def coa_balance_version_key(company_id: int) -> str:
    return f"v:coa:balance:c{int(company_id)}"
