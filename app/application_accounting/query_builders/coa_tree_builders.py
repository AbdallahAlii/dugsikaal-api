
from __future__ import annotations
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict
import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, BadRequest

from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

# Adjust path if yours differs
from app.application_accounting.chart_of_accounts.models import Account, AccountBalance
from app.application_org.models.company import Company


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _require_int(v: Any, label: str) -> int:
    try:
        iv = int(str(v).strip())
    except Exception:
        raise BadRequest(f"Invalid {label}.")
    return iv

def _normalize_depth(depth: Optional[int]) -> int:
    """depth <= 0 means infinite."""
    if depth is None:
        return 2
    try:
        d = int(depth)
    except Exception:
        raise BadRequest("Invalid depth.")
    return 10**9 if d <= 0 else d

def _get_company_row(s: Session, company_id: int) -> Tuple[int, str]:
    co = s.execute(select(Company.id, Company.name).where(Company.id == company_id)).first()
    if not co:
        raise NotFound("Company not found.")
    return int(co.id), co.name

def _fetch_accounts(s: Session, company_id: int) -> List[dict]:
    rows = (
        s.execute(
            select(
                Account.id,
                Account.parent_account_id,
                Account.code,
                Account.name,
                Account.is_group,
            ).where(Account.company_id == company_id)
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]

def _fetch_balances_map(s: Session, account_ids: List[int]) -> Dict[int, float]:
    if not account_ids:
        return {}
    rows = (
        s.execute(
            select(AccountBalance.account_id, AccountBalance.current_balance)
            .where(AccountBalance.account_id.in_(account_ids))
        )
        .all()
    )
    m = {int(aid): float(cb or 0.0) for (aid, cb) in rows}
    for aid in account_ids:
        if aid not in m:
            m[aid] = 0.0
    return m

def _code_sort_key(code: Optional[str]):
    """
    ERP-ish sorting:
      - numeric or numeric ranges get numeric sort (e.g., 5108 < 51081 < 51082)
      - anything else -> case-insensitive lexicographic
    """
    s = str(code or "")
    m = re.fullmatch(r'(\d+)(?:-(\d+))?', s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2) or -1)
        return (0, a, b)
    return (1, s.lower())

def _build_maps(accounts: List[dict]) -> Tuple[Dict[int, dict], Dict[Optional[int], List[int]]]:
    accounts_by_id: Dict[int, dict] = {}
    children_map: Dict[Optional[int], List[int]] = defaultdict(list)
    for r in accounts:
        rid = int(r["id"])
        pid = int(r["parent_account_id"]) if r["parent_account_id"] is not None else None
        accounts_by_id[rid] = r
        children_map[pid].append(rid)

    for pid, lst in children_map.items():
        lst.sort(key=lambda cid: _code_sort_key(accounts_by_id[cid]["code"]))
    return accounts_by_id, children_map

def _aggregate_balances(
    accounts_by_id: Dict[int, dict],
    children_map: Dict[Optional[int], List[int]],
    leaf_balance: Dict[int, float],
) -> Dict[int, float]:
    """
    ERPNext behavior: group balance = sum of all descendants.
    Leaf (is_group=False) balance = cached GL current_balance.
    """
    computed: Dict[int, float] = {}

    def dfs_total(aid: int) -> float:
        if aid in computed:
            return computed[aid]
        node = accounts_by_id[aid]
        if not node["is_group"]:
            total = float(leaf_balance.get(aid, 0.0))
        else:
            total = 0.0
            for cid in children_map.get(aid, []):
                total += dfs_total(cid)
        computed[aid] = total
        return total

    for aid in accounts_by_id.keys():
        dfs_total(aid)
    return computed

def _to_node(acc: dict, balance: Optional[float], include_balances: bool) -> Dict[str, Any]:
    node = {
        "id": int(acc["id"]),
        "parent_account_id": int(acc["parent_account_id"]) if acc["parent_account_id"] is not None else None,
        "code": acc["code"],
        "name": acc["name"],
        "is_group": bool(acc["is_group"]),
    }
    if include_balances:
        node["balance"] = float(balance or 0.0)
    return node

def _build_nodes_tree(
    accounts_by_id: Dict[int, dict],
    children_map: Dict[Optional[int], List[int]],
    aggregated_balance: Dict[int, float],
    roots: List[int],
    depth: int,
    include_balances: bool,
) -> List[Dict[str, Any]]:
    eff_depth = _normalize_depth(depth)

    def build(aid: int, lvl: int) -> Dict[str, Any]:
        acc = accounts_by_id[aid]
        node = _to_node(acc, aggregated_balance.get(aid), include_balances)
        if acc["is_group"] and lvl < eff_depth:
            kids = []
            for cid in children_map.get(aid, []):
                kids.append(build(cid, lvl + 1))
            if kids:
                node["children"] = kids
        return node

    return [build(rid, 1) for rid in roots]


# ─────────────────────────────────────────────────────────────
# Public Loaders
# ─────────────────────────────────────────────────────────────

def load_coa_tree(
    s: Session,
    ctx: AffiliationContext,
    company_id: int,
    *,
    root_id: Optional[int] = None,
    depth: int = 2,
    include_balances: bool = True,
    include_company_context: bool = True,
    unwrap_single_root: bool = True,   # kept for compatibility; now means "if 1 chart root, return just that node"
) -> Dict[str, Any]:
    """
    Return REAL chart root(s); never wrap with a synthetic company node.
    If there is a single chart root (common), return only that node (e.g., HJI-COA).
    """
    company_id = _require_int(company_id, "company_id")
    ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=None)

    _, co_name = _get_company_row(s, company_id)

    accounts = _fetch_accounts(s, company_id)
    if not accounts:
        payload = {"nodes": []}
        if include_company_context:
            payload["company"] = {"id": company_id, "name": co_name}
        return payload

    accounts_by_id, children_map = _build_maps(accounts)

    if include_balances:
        leaf_ids = [aid for aid, a in accounts_by_id.items() if not a["is_group"]]
        leaf_balance = _fetch_balances_map(s, leaf_ids)
        aggregated_balance = _aggregate_balances(accounts_by_id, children_map, leaf_balance)
    else:
        aggregated_balance = {}

    # Specific subtree requested
    if root_id is not None:
        rid = _require_int(root_id, "root_id")
        if rid not in accounts_by_id:
            raise NotFound("Account not found in this company.")
        nodes = _build_nodes_tree(
            accounts_by_id, children_map, aggregated_balance,
            [rid], depth, include_balances
        )
        payload = {"nodes": nodes}
        if include_company_context:
            payload["company"] = {"id": company_id, "name": co_name}
        return payload

    # --- Return real roots, never a synthetic company node ---
    top_level_ids = children_map.get(None, [])

    # If there is exactly one chart root, return that one node
    if unwrap_single_root and len(top_level_ids) == 1:
        nodes = _build_nodes_tree(
            accounts_by_id, children_map, aggregated_balance,
            [top_level_ids[0]], depth, include_balances
        )
        payload = {"nodes": nodes}
        if include_company_context:
            payload["company"] = {"id": company_id, "name": co_name}
        return payload

    # Otherwise (multiple real roots, unusual), return them as siblings
    nodes = _build_nodes_tree(
        accounts_by_id, children_map, aggregated_balance,
        top_level_ids, depth, include_balances
    )
    payload = {"nodes": nodes}
    if include_company_context:
        payload["company"] = {"id": company_id, "name": co_name}
    return payload


def load_coa_children(
    s: Session,
    ctx: AffiliationContext,
    company_id: int,
    *,
    parent_id: int,
    include_balances: bool = True,
) -> Dict[str, Any]:
    company_id = _require_int(company_id, "company_id")
    parent_id = _require_int(parent_id, "parent_id")
    ensure_scope_by_ids(context=ctx, target_company_id=company_id, target_branch_id=None)

    accounts = _fetch_accounts(s, company_id)
    if not accounts:
        return {"parent_id": str(parent_id), "children": []}

    accounts_by_id, children_map = _build_maps(accounts)
    if parent_id not in accounts_by_id:
        raise NotFound("Parent account not found in this company.")

    if include_balances:
        leaf_ids = [aid for aid, a in accounts_by_id.items() if not a["is_group"]]
        leaf_balance = _fetch_balances_map(s, leaf_ids)
        aggregated_balance = _aggregate_balances(accounts_by_id, children_map, leaf_balance)
    else:
        aggregated_balance = {}

    nodes: List[Dict[str, Any]] = []
    for cid in children_map.get(parent_id, []):
        acc = accounts_by_id[cid]
        nodes.append(_to_node(acc, aggregated_balance.get(cid), include_balances))

    return {"parent_id": str(parent_id), "children": nodes}
