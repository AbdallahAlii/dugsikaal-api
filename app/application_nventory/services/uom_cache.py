
# app/application_nventory/services/uom_cache.py
from __future__ import annotations

import logging
from typing import Optional
from sqlalchemy import text
from config.database import db
from app.common.cache.hash_cache import hget_json, hset_json
from app.common.cache.cache_keys import uom_item_hash_key


def get_uom_factor(*, item_id: int, uom_id: int, base_uom_id: Optional[int] = None) -> Optional[float]:
    """
    Returns factor where: 1 [uom_id] = factor [base_uom].
    """
    logging.info(f"🔍 UOM Factor lookup - item_id: {item_id}, uom_id: {uom_id}, base_uom_id: {base_uom_id}")

    if base_uom_id and uom_id == base_uom_id:
        logging.info(f"  ➡️ Same UOM, returning 1.0")
        return 1.0

    hk = uom_item_hash_key(item_id)
    cached = hget_json(hk, str(uom_id))
    if cached is not None:
        logging.info(f"  ➡️ Cache hit: factor={cached}")
        return float(cached)

    # 🚨 DEBUG: Log the SQL query
    logging.info(f"  🔍 Cache miss - querying database...")

    row = db.session.execute(
        text("""
             SELECT conversion_factor
             FROM uom_conversions
             WHERE item_id = :i
               AND uom_id = :u
               AND is_active = true LIMIT 1
             """),
        {"i": item_id, "u": uom_id},
    ).first()

    if not row:
        logging.warning(f"  ❌ No UOM conversion found for item_id={item_id}, uom_id={uom_id}")
        return None

    factor = float(row[0])
    logging.info(f"  ✅ Database result: factor={factor}")
    hset_json(hk, str(uom_id), factor)
    return factor