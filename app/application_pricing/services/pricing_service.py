from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional, Iterable, Dict, List, Tuple

from sqlalchemy import select
from config.database import db

from app.application_pricing.repo.pricing_repo import PricingRepository
from app.application_pricing.services.price_day_cache import get_rate_from_snapshot
from app.application_nventory.inventory_models import PriceList, PriceListType, Item

log = logging.getLogger(__name__)

def _now_utc() -> datetime:
    return datetime.utcnow()

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)

# ----- Helpers to resolve Price List by target type -----

def _resolve_default_price_list_id(company_id: int, target: PriceListType) -> Optional[int]:
    """
    Company default: first active PL of the requested type or BOTH.
    """
    q = (
        select(PriceList.id)
        .where(
            PriceList.company_id == company_id,
            PriceList.is_active == True,  # noqa: E712
            PriceList.list_type.in_([target, PriceListType.BOTH]),
        )
        .order_by(PriceList.id.asc())
        .limit(1)
    )
    row = db.session.execute(q).first()
    return int(row[0]) if row else None

def _get_effective_pl(
    company_id: int,
    explicit_pl_id: Optional[int],
    explicit_pl_name: Optional[str],
    party_id: Optional[int],  # optional (Customer or Supplier)
    target: PriceListType,    # SELLING or BUYING
) -> Tuple[int, bool]:
    """
    Returns: (price_list_id, price_not_uom_dependent)
    Precedence: explicit (id/name) → TODO: party default (if you add that later) → company default (by target).
    """
    repo = PricingRepository()

    # 1) Explicit ID
    if explicit_pl_id:
        pl = repo.get_price_list(company_id, price_list_id=int(explicit_pl_id), price_list_name=None)
        if pl and pl["active"]:
            return int(pl["id"]), bool(pl["pnu"])

    # 2) Explicit Name
    if explicit_pl_name:
        pl = repo.get_price_list(company_id, price_list_id=None, price_list_name=explicit_pl_name)
        if pl and pl["active"]:
            return int(pl["id"]), bool(pl["pnu"])

    # 3) (Optional) party default could be added here if you store it per party (customer/supplier)

    # 4) Company default by target
    did = _resolve_default_price_list_id(company_id, target)
    if not did:
        # safe fallback; treat as PNU to avoid UOM specificity
        return 0, True
    pl = repo.get_price_list(company_id, price_list_id=did, price_list_name=None)
    return (int(pl["id"]), bool(pl["pnu"])) if pl else (0, True)

# ----- Snapshot (used only for exact keys) -----

def _get_snapshot_price(
    *,
    company_id: int,
    branch_id: Optional[int],
    pl_id: int,
    item_id: int,
    uom_id: Optional[int],
    on: datetime,
    prefer_null_uom: bool,
) -> Optional[float]:
    """
    Try a single exact lookup in the day snapshot.
    - If prefer_null_uom=True, we check the normalized NULL-uom key first.
    - If uom_id is provided, we can check that key.
    Note: we DO NOT do any conversion; rate is returned as stored.
    """
    # NULL-uom is normalized by the snapshot to 'PU' param (we pass item base in caller only if you keep that),
    # but we can just pass uom_id (None here) and let SQL fallback do the rest. For simplicity, snapshot is used
    # only when we have a concrete UOM intent (either NULL or a given one). Otherwise we skip to SQL.
    # In this simplified version we call SQL directly from service (see below).
    return None  # intentionally disabled to keep behavior predictable for your no-UOM-conv rule

# ----- Public resolvers -----

def get_selling_rate_basic(
    *,
    company_id: int,
    branch_id: Optional[int],
    item_id: int,
    txn_uom_id: Optional[int],   # None → no UOM preference
    qty: Optional[float] = None,
    posting_date: Optional[datetime] = None,
    price_list_id: Optional[int] = None,
    price_list_name: Optional[str] = None,
    customer_id: Optional[int] = None,
) -> Dict:
    repo = PricingRepository()
    when = posting_date or _now_utc()

    # Item core
    ic = repo.get_item_core(company_id, item_id)
    if not ic or not ic["is_active"]:
        out = {
            "item_id": item_id,
            "txn_uom_id": txn_uom_id or ic.get("base_uom_id"),
            "rate": 0.0,
            "stock_factor": 1.0,
            "used_price_list_id": 0,
            "used_branch_id": branch_id,
            "price_source": "none",
        }
        if qty is not None:
            out["line_amount"] = 0.0
            out["stock_qty_change"] = 0.0
        return out

    pl_id, pnu = _get_effective_pl(
        company_id=company_id,
        explicit_pl_id=price_list_id,
        explicit_pl_name=price_list_name,
        party_id=customer_id,
        target=PriceListType.SELLING,
    )
    if not pl_id:
        out = {
            "item_id": item_id,
            "txn_uom_id": txn_uom_id or ic["base_uom_id"],
            "rate": 0.0,
            "stock_factor": 1.0,
            "used_price_list_id": 0,
            "used_branch_id": branch_id,
            "price_source": "none",
        }
        if qty is not None:
            out["line_amount"] = 0.0
            out["stock_qty_change"] = qty or 0.0
        return out

    # Direct SQL resolution (no UOM conversion)
    res = repo.find_item_price(
        company_id=company_id,
        item_id=item_id,
        price_list_id=pl_id,
        branch_id=branch_id,
        uom_id=txn_uom_id,
        at=when,
        pnu=pnu,
    )

    if res:
        rate = float(res["rate"])
        src = f"item_price_{res['source']}"
    else:
        rate = 0.0
        src = "none"
        log.debug("selling: NO RATE company=%s branch=%s pl=%s item=%s txn=%s",
                  company_id, branch_id, pl_id, item_id, txn_uom_id)

    out = {
        "item_id": item_id,
        "txn_uom_id": txn_uom_id or ic["base_uom_id"],
        "rate": rate,
        "stock_factor": 1.0,  # always 1.0 (no conversion)
        "used_price_list_id": pl_id,
        "used_branch_id": branch_id,
        "price_source": src,
    }
    if qty is not None:
        out["line_amount"] = rate * float(qty)
        out["stock_qty_change"] = float(qty)  # no conversion
    return out


def get_buying_rate_basic(
    *,
    company_id: int,
    branch_id: Optional[int],
    item_id: int,
    txn_uom_id: Optional[int],   # None → no UOM preference
    qty: Optional[float] = None,
    posting_date: Optional[datetime] = None,
    price_list_id: Optional[int] = None,
    price_list_name: Optional[str] = None,
    supplier_id: Optional[int] = None,
) -> Dict:
    repo = PricingRepository()
    when = posting_date or _now_utc()

    ic = repo.get_item_core(company_id, item_id)
    if not ic or not ic["is_active"]:
        out = {
            "item_id": item_id,
            "txn_uom_id": txn_uom_id or ic.get("base_uom_id"),
            "rate": 0.0,
            "stock_factor": 1.0,
            "used_price_list_id": 0,
            "used_branch_id": branch_id,
            "price_source": "none",
        }
        if qty is not None:
            out["line_amount"] = 0.0
            out["stock_qty_change"] = 0.0
        return out

    pl_id, pnu = _get_effective_pl(
        company_id=company_id,
        explicit_pl_id=price_list_id,
        explicit_pl_name=price_list_name,
        party_id=supplier_id,
        target=PriceListType.BUYING,
    )
    if not pl_id:
        out = {
            "item_id": item_id,
            "txn_uom_id": txn_uom_id or ic["base_uom_id"],
            "rate": 0.0,
            "stock_factor": 1.0,
            "used_price_list_id": 0,
            "used_branch_id": branch_id,
            "price_source": "none",
        }
        if qty is not None:
            out["line_amount"] = 0.0
            out["stock_qty_change"] = qty or 0.0
        return out

    res = repo.find_item_price(
        company_id=company_id,
        item_id=item_id,
        price_list_id=pl_id,
        branch_id=branch_id,
        uom_id=txn_uom_id,
        at=when,
        pnu=pnu,
    )

    if res:
        rate = float(res["rate"])
        src = f"item_price_{res['source']}"
    else:
        rate = 0.0
        src = "none"
        log.debug("buying: NO RATE company=%s branch=%s pl=%s item=%s txn=%s",
                  company_id, branch_id, pl_id, item_id, txn_uom_id)

    out = {
        "item_id": item_id,
        "txn_uom_id": txn_uom_id or ic["base_uom_id"],
        "rate": rate,
        "stock_factor": 1.0,
        "used_price_list_id": pl_id,
        "used_branch_id": branch_id,
        "price_source": src,
    }
    if qty is not None:
        out["line_amount"] = rate * float(qty)
        out["stock_qty_change"] = float(qty)
    return out
