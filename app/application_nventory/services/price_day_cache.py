# app/application_nventory/services/price_day_cache.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import text

from config.database import db

from app.common.cache.cache import get_version
from app.common.cache import keys
from app.common.cache.redis_client import redis_kv


SQL_ACTIVE = text("""
SELECT item_id, COALESCE(uom_id, :PU) AS uom_id, COALESCE(branch_id, 0) AS br, rate
FROM item_prices
WHERE price_list_id=:PL
  AND (valid_from IS NULL OR valid_from<=:D)
  AND (valid_upto IS NULL OR :D<=valid_upto)
""")


def _day(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _pl_day_version_key(company_id: int, pl_id: int) -> str:
    """
    Version key for a (company, price_list) day snapshot namespace.
    Call bump_version(keys.v_company("price_list:<pl_id>", company_id)) if you ever need to invalidate.
    """
    return keys.v_company(f"price_list:{int(pl_id)}", int(company_id))


def _pl_day_hash_key(company_id: int, pl_id: int, version: int, day: str) -> str:
    """
    Redis HASH key holding the per-day snapshot.
    We keep it explicit (not part of doclist/docdetail) because this is a special cache.
    """
    return f"plday:{int(company_id)}:{int(pl_id)}:v{int(version)}:{day}"


def _hget_json(hk: str, field: str) -> Optional[dict]:
    raw = redis_kv.hget(hk, field)
    if not raw:
        return None
    try:
        import json
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _hset_json(hk: str, field: str, value: dict, *, ttl: int) -> None:
    try:
        import json
        payload = json.dumps(value, default=str, separators=(",", ":"))
    except Exception:
        return
    try:
        redis_kv.hset(hk, field, payload)
        # expire is applied to the whole hash key (fine for a daily snapshot)
        redis_kv.expire(hk, int(ttl))
    except Exception:
        # best-effort cache
        return


def get_rate_from_snapshot(
    *,
    company_id: int,
    pl_id: int,
    I: int,               # item_id
    U: int,               # uom_id
    B: int | None,        # branch_id
    D: datetime,          # day
    PU: int               # pricing_uom fallback
) -> float | None:
    """
    Tries exact (branch+UOM) then global (UOM) from a per-day snapshot hash.
    Cold builds once per (company, price_list, version, day).

    Redis:
      vkey: keys.v_company(f"price_list:{pl_id}", company_id)
      hash: plday:<company_id>:<pl_id>:v<version>:<YYYYMMDD>
      field: "<item_id>:<uom_id>:<branch_id>"
      val: {"r": <rate>}
    """
    v = get_version(_pl_day_version_key(company_id, pl_id), default=1)
    hk = _pl_day_hash_key(company_id, pl_id, v, _day(D))

    b = int(B or 0)

    key1 = f"{int(I)}:{int(U)}:{b}"
    val = _hget_json(hk, key1)
    if val is not None:
        return float(val["r"])

    key2 = f"{int(I)}:{int(U)}:0"
    val = _hget_json(hk, key2)
    if val is not None:
        return float(val["r"])

    # Cold build (best effort). Build the whole day's active rows once.
    rows = db.session.execute(SQL_ACTIVE, {"PL": int(pl_id), "D": D, "PU": int(PU)}).fetchall()
    for item_id, uom_id, br, rate in rows:
        _hset_json(
            hk,
            f"{int(item_id)}:{int(uom_id)}:{int(br or 0)}",
            {"r": float(rate)},
            ttl=3600,
        )

    # Retry after build
    val = _hget_json(hk, key1) or _hget_json(hk, key2)
    return float(val["r"]) if val is not None else None