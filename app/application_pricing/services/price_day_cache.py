from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from config.database import db
from app.common.cache.redis_client import redis_kv
from app.common.cache.cache import get_version, bump_version

log = logging.getLogger(__name__)

# ---------- Redis key helpers (keep local to module) ----------
def _vkey(company_id: int, pl_id: int) -> str:
    # version counter for this price list
    return f"v:plist:{int(company_id)}:{int(pl_id)}"

def _day(d: datetime) -> str:
    return d.strftime("%Y%m%d")

def _hk(company_id: int, pl_id: int, version: int, day_yyyymmdd: str) -> str:
    # snapshot hash key (one hash per price list version per day)
    return f"plist:c{int(company_id)}:pl{int(pl_id)}:v{int(version)}:d{day_yyyymmdd}"

def _hget_json(hash_key: str, field: str) -> Optional[dict]:
    raw = redis_kv.hget(hash_key, field)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

def _hset_json(hash_key: str, field: str, value: dict) -> bool:
    try:
        payload = json.dumps(value, separators=(",", ":"), default=str)
    except Exception:
        return False
    return bool(redis_kv.hset(hash_key, field, payload))

# ---------- SQL ----------
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

# Fallback query when Redis is down: fetch only candidates for 1 item/uom
SQL_RATE_ONE = text("""
SELECT COALESCE(branch_id, 0) AS br, rate
FROM item_prices
WHERE price_list_id = :PL
  AND item_id = :I
  AND COALESCE(uom_id, :PU) = :U
  AND (valid_from IS NULL OR valid_from <= :D)
  AND (valid_upto IS NULL OR :D <= valid_upto)
ORDER BY CASE WHEN COALESCE(branch_id, 0) = :B THEN 0 ELSE 1 END
LIMIT 50
""")

# ---------- Public API ----------
def bump_price_list_version(company_id: int, pl_id: int) -> int:
    """
    Best-effort version bump. If Redis is down, returns 0 and nothing breaks.
    """
    v = bump_version(_vkey(company_id, pl_id))
    log.debug("price_day_cache.bump_version: company=%s pl=%s -> v=%s", company_id, pl_id, v)
    return v

def get_rate_from_snapshot(
    *,
    company_id: int,
    pl_id: int,
    I: int,
    U: int,
    B: int | None,
    D: datetime,
    PU: int,
) -> float | None:
    """
    Reads a day snapshot from Redis hash. If missing, builds the snapshot for that day.
    Redis optional:
      - Redis up   -> snapshot caching
      - Redis down -> DB-only lookup (no crash)
    """
    b = int(B or 0)

    # If Redis is not reachable, do DB-only lookup (fast + safe)
    if not redis_kv.ping():
        return _get_rate_db_only(pl_id=pl_id, I=int(I), U=int(U), B=b, D=D, PU=int(PU))

    v = get_version(_vkey(company_id, pl_id), default=1)
    hk = _hk(company_id, pl_id, v, _day(D))

    key_exact = f"{int(I)}:{int(U)}:{b}"
    key_global = f"{int(I)}:{int(U)}:0"

    val = _hget_json(hk, key_exact)
    if val is not None:
        return float(val["r"])

    val = _hget_json(hk, key_global)
    if val is not None:
        return float(val["r"])

    # Cold build (fill snapshot for the day)
    try:
        rows = db.session.execute(SQL_ACTIVE, {"PL": pl_id, "D": D, "PU": PU}).fetchall()
    except Exception as e:
        log.exception("price_day_cache DB build failed pl=%s day=%s: %s", pl_id, _day(D), e)
        return None

    # Write snapshot best-effort (if writes fail, still return correct DB result)
    wrote_any = False
    for item_id, uom_id, br, rate in rows:
        f = f"{int(item_id)}:{int(uom_id)}:{int(br)}"
        if _hset_json(hk, f, {"r": float(rate)}):
            wrote_any = True

    # Set TTL on the hash key once (even if partial)
    if wrote_any:
        redis_kv.expire(hk, 3600)

    # Retry read after build
    val = _hget_json(hk, key_exact) or _hget_json(hk, key_global)
    if val is None:
        return None
    return float(val["r"])

# ---------- Internal ----------
def _get_rate_db_only(*, pl_id: int, I: int, U: int, B: int, D: datetime, PU: int) -> float | None:
    """
    Redis-down fallback: query DB for specific item/uom, prefer branch match then global (branch 0).
    """
    try:
        rows = db.session.execute(
            SQL_RATE_ONE,
            {"PL": pl_id, "I": I, "U": U, "B": B, "D": D, "PU": PU},
        ).fetchall()
    except Exception as e:
        log.exception("price_day_cache DB-only lookup failed: %s", e)
        return None

    # Prefer exact branch if present, else branch 0
    best_exact = None
    best_global = None
    for br, rate in rows:
        br = int(br or 0)
        if br == B and best_exact is None:
            best_exact = float(rate)
        if br == 0 and best_global is None:
            best_global = float(rate)

    return best_exact if best_exact is not None else best_global