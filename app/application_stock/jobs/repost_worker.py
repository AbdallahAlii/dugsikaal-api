# stock/jobs/repost_worker.py
from __future__ import annotations
from datetime import datetime
from typing import Iterable, Tuple, List, Dict, Set

from config.database import db
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.bin_derive import derive_bin


def run_repost_batch(tasks: Iterable[Tuple[int, int, int, datetime]]) -> None:
    """
    tasks: iterable of (company_id, item_id, warehouse_id, start_dt)
    Coalesce duplicates and run sequentially (or dispatch to your queue system).
    """
    seen: Set[Tuple[int, int, int, datetime]] = set(tasks)
    for (company_id, item_id, wh_id, start_dt) in seen:
        with db.session.begin():
            repost_from(company_id=company_id, item_id=item_id, warehouse_id=wh_id, start_dt=start_dt)
            derive_bin(item_id, wh_id)
