
# app/application_stock/engine/selectors.py
from __future__ import annotations
from datetime import datetime
from typing import List
from sqlalchemy import select, and_, or_
from config.database import db
from app.application_stock.stock_models import StockLedgerEntry

def get_last_sle_before_dt(
    company_id: int,
    item_id: int,
    warehouse_id: int,
    before_dt: datetime,
) -> StockLedgerEntry | None:
    """
    The last NON-CANCELLED SLE at or before 'before_dt'.
    Inclusive on same timestamp so sequential posts at the same moment chain correctly.
    """
    stmt = (
        select(StockLedgerEntry)
        .where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            or_(
                StockLedgerEntry.posting_date < before_dt.date(),
                and_(
                    StockLedgerEntry.posting_date == before_dt.date(),
                    StockLedgerEntry.posting_time <= before_dt,   # ← inclusive
                ),
            ),
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
        )
        .order_by(
            StockLedgerEntry.posting_date.desc(),
            StockLedgerEntry.posting_time.desc(),
            StockLedgerEntry.id.desc(),  # tie-breaker within same timestamp
        )
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def get_stream_from_dt(
    company_id: int,
    item_id: int,
    warehouse_id: int,
    start_dt: datetime,
) -> List[StockLedgerEntry]:
    """
    All NON-CANCELLED, NON-REVERSAL SLEs ON/AFTER start_dt, chronologically.
    """
    stmt = (
        select(StockLedgerEntry)
        .where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            or_(
                StockLedgerEntry.posting_date > start_dt.date(),
                and_(
                    StockLedgerEntry.posting_date == start_dt.date(),
                    StockLedgerEntry.posting_time >= start_dt,
                ),
            ),
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
            StockLedgerEntry.is_reversal == False,
        )
        .order_by(
            StockLedgerEntry.posting_date.asc(),
            StockLedgerEntry.posting_time.asc(),
            StockLedgerEntry.id.asc(),
        )
    )
    return list(db.session.execute(stmt).scalars().all())
