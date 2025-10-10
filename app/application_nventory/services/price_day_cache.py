# app/application_nventory/services/price_day_cache.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import text
from app.common.cache.core_cache import get_version
from app.common.cache.hash_cache import hget_json, hset_json
from app.common.cache.cache_keys import price_list_version_key, price_list_hash_key
from config.database import db

SQL_ACTIVE = text("""
SELECT item_id, COALESCE(uom_id, :PU) AS uom_id, COALESCE(branch_id, 0) AS br, rate
FROM item_prices
WHERE price_list_id=:PL
  AND (valid_from IS NULL OR valid_from<=:D)
  AND (valid_upto IS NULL OR :D<=valid_upto)
""")

def _day(d: datetime) -> str:
    return d.strftime("%Y%m%d")

def get_rate_from_snapshot(
    *, company_id: int, pl_id: int, I: int, U: int, B: int | None, D: datetime, PU: int
) -> float | None:
    """
    Tries exact (branch+UOM) then global (UOM) from a per-day snapshot hash.
    Cold builds once per (company, PL, version, day).
    """
    v = get_version(price_list_version_key(company_id, pl_id))
    hk = price_list_hash_key(company_id, pl_id, v, _day(D))

    b = B or 0
    key1 = f"{I}:{U}:{b}"
    val = hget_json(hk, key1)
    if val is not None:
        return float(val["r"])

    key2 = f"{I}:{U}:0"
    val = hget_json(hk, key2)
    if val is not None:
        return float(val["r"])

    # Cold build
    rows = db.session.execute(SQL_ACTIVE, {"PL": pl_id, "D": D, "PU": PU}).fetchall()
    for item_id, uom_id, br, rate in rows:
        hset_json(hk, f"{item_id}:{uom_id}:{br}", {"r": float(rate)}, ttl=3600)

    # Retry
    val = hget_json(hk, key1) or hget_json(hk, key2)
    return float(val["r"]) if val is not None else None
