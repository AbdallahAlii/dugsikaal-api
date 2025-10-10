# app/application_nventory/services/pricing_service.
from __future__ import annotations

from datetime import datetime
from typing import Optional, Iterable, List, Dict
from sqlalchemy import select
from config.database import db

from app.application_nventory.inventory_models import Item, PriceList, PriceListType
from app.application_nventory.services.price_day_cache import get_rate_from_snapshot
from app.application_nventory.services.uom_cache import get_uom_factor

def _today() -> datetime:
    return datetime.utcnow()

def _resolve_effective_price_list_id(company_id: int, explicit_pl_id: Optional[int] = None) -> Optional[int]:
    if explicit_pl_id:
        return int(explicit_pl_id)
    row = db.session.execute(
        select(PriceList.id)
        .where(
            PriceList.company_id == company_id,
            PriceList.is_active == True,  # noqa: E712
            PriceList.list_type.in_([PriceListType.SELLING, PriceListType.BOTH]),
        )
        .order_by(PriceList.id.asc())
        .limit(1)
    ).first()
    return int(row[0]) if row else None

def _resolve_rate(
    *,
    company_id:int, branch_id:Optional[int], item_id:int, txn_uom_id:int,
    posting_date:Optional[datetime], price_list_id:Optional[int]
) -> tuple[float, float, int, Optional[int]]:
    d = posting_date or _today()
    item = db.session.get(Item, item_id)
    if not item or not item.base_uom_id:
        return 0.0, 1.0, 0, branch_id

    PU = int(item.base_uom_id)
    PL = _resolve_effective_price_list_id(company_id, price_list_id) or 0
    if not PL:
        return 0.0, 1.0, 0, branch_id

    r = get_rate_from_snapshot(company_id=company_id, pl_id=PL, I=item_id, U=txn_uom_id, B=branch_id, D=d, PU=PU)
    if r is None:
        factor = get_uom_factor(item_id=item_id, from_uom_id=txn_uom_id, base_uom_id=PU)
        if factor:
            rb = get_rate_from_snapshot(company_id=company_id, pl_id=PL, I=item_id, U=PU, B=branch_id, D=d, PU=PU)
            if rb is None:
                rb = get_rate_from_snapshot(company_id=company_id, pl_id=PL, I=item_id, U=PU, B=None, D=d, PU=PU)
            r = (rb * factor) if rb is not None else 0.0
        else:
            r = 0.0

    stock_factor = get_uom_factor(item_id=item_id, from_uom_id=txn_uom_id, base_uom_id=PU) or 1.0
    return float(r), float(stock_factor), PL, branch_id

def get_selling_rate_basic(
    *,
    company_id:int, branch_id:Optional[int], item_id:int, txn_uom_id:int,
    posting_date:Optional[datetime], price_list_id:Optional[int], qty: Optional[float] = None
) -> Dict:
    rate, stock_factor, PL, B = _resolve_rate(
        company_id=company_id, branch_id=branch_id, item_id=item_id, txn_uom_id=txn_uom_id,
        posting_date=posting_date, price_list_id=price_list_id
    )
    out: Dict = {
        "item_id": item_id,
        "txn_uom_id": txn_uom_id,
        "rate": rate,
        "stock_factor": stock_factor,
        "used_price_list_id": PL,
        "used_branch_id": B,
    }
    if qty is not None:
        out["line_amount"] = rate * float(qty)
        out["stock_qty_change"] = float(qty) * stock_factor
    return out

def get_selling_rate_batch(
    *,
    company_id:int, branch_id:Optional[int],
    items: Iterable[Dict[str, int | float]],
    posting_date:Optional[datetime], price_list_id:Optional[int]
) -> List[Dict]:
    results: List[Dict] = []
    for it in items:
        item_id = int(it["item_id"])
        txn_uom_id = int(it["txn_uom_id"])
        qty = float(it["qty"]) if ("qty" in it and it["qty"] is not None) else None
        res = get_selling_rate_basic(
            company_id=company_id, branch_id=branch_id, item_id=item_id, txn_uom_id=txn_uom_id,
            posting_date=posting_date, price_list_id=price_list_id, qty=qty
        )
        results.append(res)
    return results
