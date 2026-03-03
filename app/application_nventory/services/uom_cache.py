# app/application_nventory/services/uom_cache.py
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from config.database import db
from app.common.cache.redis_client import redis_kv

log = logging.getLogger(__name__)


def _uom_item_hash_key(item_id: int) -> str:
    """
    Redis HASH key for UOM conversions per item.
    Field: "<uom_id>" -> JSON: {"f": <factor>}
    """
    return f"uom:item:{int(item_id)}"


def _hget_json(hk: str, field: str) -> Optional[dict]:
    raw = redis_kv.hget(hk, field)
    if not raw:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return None


def _hset_json(hk: str, field: str, value: dict, *, ttl: int) -> None:
    try:
        payload = json.dumps(value, default=str, separators=(",", ":"))
    except Exception:
        return
    try:
        redis_kv.hset(hk, field, payload)
        redis_kv.expire(hk, int(ttl))  # TTL applies to the whole hash
    except Exception:
        # best-effort cache
        return


def get_uom_factor(*, item_id: int, uom_id: int, base_uom_id: Optional[int] = None) -> Optional[float]:
    """
    Returns factor where: 1 [uom_id] = factor [base_uom].

    Uses Redis HASH cache per item:
      key   = "uom:item:<item_id>"
      field = "<uom_id>"
      val   = {"f": <factor>}
    """
    log.debug("UOM Factor lookup item_id=%s uom_id=%s base_uom_id=%s", item_id, uom_id, base_uom_id)

    item_id = int(item_id)
    uom_id = int(uom_id)
    if base_uom_id is not None:
        base_uom_id = int(base_uom_id)

    # Same UOM => factor 1
    if base_uom_id and uom_id == base_uom_id:
        return 1.0

    hk = _uom_item_hash_key(item_id)

    cached = _hget_json(hk, str(uom_id))
    if cached is not None and "f" in cached:
        try:
            return float(cached["f"])
        except Exception:
            pass

    # Cache miss -> DB
    row = db.session.execute(
        text("""
            SELECT conversion_factor
            FROM uom_conversions
            WHERE item_id = :i
              AND uom_id = :u
              AND is_active = true
            LIMIT 1
        """),
        {"i": item_id, "u": uom_id},
    ).first()

    if not row:
        return None

    factor = float(row[0])

    # Cache result (best effort)
    _hset_json(hk, str(uom_id), {"f": factor}, ttl=24 * 3600)

    return factor