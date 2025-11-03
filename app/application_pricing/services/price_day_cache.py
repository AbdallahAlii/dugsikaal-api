# # app/application_nventory/services/price_day_cache.py
from __future__ import annotations
import logging
from datetime import datetime
from sqlalchemy import text
from app.common.cache.core_cache import get_version
from app.common.cache.core_cache import bump_version as _bump_version
from app.common.cache.hash_cache import hget_json, hset_json
from app.common.cache.cache_keys import price_list_version_key, price_list_hash_key
from config.database import db

log = logging.getLogger(__name__)

SQL_ACTIVE = text("""
SELECT item_id,
       COALESCE(uom_id, :PU) AS uom_id,
       COALESCE(branch_id, 0) AS br,
       rate
FROM item_prices
WHERE price_list_id = :PL
  AND (valid_from IS NULL OR valid_from <= :D)
  AND (valid_upto IS NULL OR :D <= valid_upto)
""")

def _day(d: datetime) -> str:
    return d.strftime("%Y%m%d")

def bump_price_list_version(company_id: int, pl_id: int) -> None:
    try:
        _bump_version(price_list_version_key(company_id, pl_id))
        log.debug("price_day_cache.bump_version: company=%s pl=%s", company_id, pl_id)
    except Exception:
        # Safe ignore if core doesn't support it
        pass

def get_rate_from_snapshot(
    *, company_id: int, pl_id: int, I: int, U: int, B: int | None, D: datetime, PU: int
) -> float | None:
    v = get_version(price_list_version_key(company_id, pl_id))
    hk = price_list_hash_key(company_id, pl_id, v, _day(D))

    b = B or 0
    key_exact = f"{I}:{U}:{b}"
    key_global = f"{I}:{U}:0"

    val = hget_json(hk, key_exact)
    if val is not None:
        log.debug("snapshot HIT exact hk=%s key=%s rate=%s", hk, key_exact, val)
        return float(val["r"])

    val = hget_json(hk, key_global)
    if val is not None:
        log.debug("snapshot HIT global hk=%s key=%s rate=%s", hk, key_global, val)
        return float(val["r"])

    # cold build (fill all branches/UOMs for the day)
    rows = db.session.execute(SQL_ACTIVE, {"PL": pl_id, "D": D, "PU": PU}).fetchall()
    log.debug("snapshot COLD BUILD hk=%s rows=%s (company=%s pl=%s day=%s)", hk, len(rows), company_id, pl_id, _day(D))
    for item_id, uom_id, br, rate in rows:
        k = f"{int(item_id)}:{int(uom_id)}:{int(br)}"
        hset_json(hk, k, {"r": float(rate)}, ttl=3600)

    # retry
    val = hget_json(hk, key_exact) or hget_json(hk, key_global)
    if val is None:
        log.debug("snapshot MISS hk=%s item=%s uom=%s branch=%s", hk, I, U, b)
        return None
    log.debug("snapshot HIT after build hk=%s key=%s rate=%s", hk, key_exact if hget_json(hk, key_exact) else key_global, val)
    return float(val["r"])
