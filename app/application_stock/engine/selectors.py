#
# # app/application_stock/engine/selectors.py
# from __future__ import annotations
# from datetime import datetime
# from typing import List
# from sqlalchemy import select, and_, or_
# from config.database import db
# from app.application_stock.stock_models import StockLedgerEntry
#
# def get_last_sle_before_dt(
#     company_id: int,
#     item_id: int,
#     warehouse_id: int,
#     before_dt: datetime,
# ) -> StockLedgerEntry | None:
#     """
#     The last NON-CANCELLED SLE at or before 'before_dt'.
#     Inclusive on same timestamp so sequential posts at the same moment chain correctly.
#     """
#     stmt = (
#         select(StockLedgerEntry)
#         .where(
#             StockLedgerEntry.company_id == company_id,
#             StockLedgerEntry.item_id == item_id,
#             StockLedgerEntry.warehouse_id == warehouse_id,
#             or_(
#                 StockLedgerEntry.posting_date < before_dt.date(),
#                 and_(
#                     StockLedgerEntry.posting_date == before_dt.date(),
#                     StockLedgerEntry.posting_time <= before_dt,   # ← inclusive
#                 ),
#             ),
#             StockLedgerEntry.is_cancelled == False,  # noqa: E712
#         )
#         .order_by(
#             StockLedgerEntry.posting_date.desc(),
#             StockLedgerEntry.posting_time.desc(),
#             StockLedgerEntry.id.desc(),  # tie-breaker within same timestamp
#         )
#         .limit(1)
#     )
#     return db.session.execute(stmt).scalar_one_or_none()
#
#
# def get_stream_from_dt(
#     company_id: int,
#     item_id: int,
#     warehouse_id: int,
#     start_dt: datetime,
# ) -> List[StockLedgerEntry]:
#     """
#     All NON-CANCELLED, NON-REVERSAL SLEs ON/AFTER start_dt, chronologically.
#     """
#     stmt = (
#         select(StockLedgerEntry)
#         .where(
#             StockLedgerEntry.company_id == company_id,
#             StockLedgerEntry.item_id == item_id,
#             StockLedgerEntry.warehouse_id == warehouse_id,
#             or_(
#                 StockLedgerEntry.posting_date > start_dt.date(),
#                 and_(
#                     StockLedgerEntry.posting_date == start_dt.date(),
#                     StockLedgerEntry.posting_time >= start_dt,
#                 ),
#             ),
#             StockLedgerEntry.is_cancelled == False,  # noqa: E712
#             StockLedgerEntry.is_reversal == False,
#         )
#         .order_by(
#             StockLedgerEntry.posting_date.asc(),
#             StockLedgerEntry.posting_time.asc(),
#             StockLedgerEntry.id.asc(),
#         )
#     )
#     return list(db.session.execute(stmt).scalars().all())
# app/application_stock/engine/selectors.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_stock.stock_models import StockLedgerEntry, Bin

__all__ = [
    "get_current_valuation_rate",
    "get_last_sle_before_dt",
    "get_stream_from_dt",
]


# ---------- Helpers ----------

def _to_dec(val) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return None


# ---------- Valuation lookups ----------

def get_current_valuation_rate(
    s: Session,
    company_id: int,
    item_id: int,
    warehouse_id: int,
) -> Optional[Decimal]:
    """
    Fast valuation rate resolver for issues/receipts.

    Resolution order (O(1) lookups with your indexes/constraints):
      1) BIN snapshot: use Bin.valuation_rate for (company,item,warehouse)
      2) Latest non-cancelled SLE.valuation_rate for (company,item,warehouse)
      3) None (caller may coalesce to Decimal('0'))

    Notes:
      - Bin has a persisted computed stock_value = actual_qty * valuation_rate, so
        using Bin.valuation_rate is the cheapest & most current snapshot.
      - Falls back to the last SLE valuation_rate to avoid zero rates on empty bins.
    """
    # 1) BIN first (unique on company_id,item_id,warehouse_id)
    rate = s.execute(
        select(Bin.valuation_rate).where(
            Bin.company_id == company_id,
            Bin.item_id == item_id,
            Bin.warehouse_id == warehouse_id,
        )
    ).scalar_one_or_none()
    if rate is not None:
        return _to_dec(rate)

    # 2) Latest non-cancelled SLE valuation_rate
    rate = s.execute(
        select(StockLedgerEntry.valuation_rate).where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
        )
        .order_by(
            StockLedgerEntry.posting_date.desc(),
            StockLedgerEntry.posting_time.desc(),
            StockLedgerEntry.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    return _to_dec(rate)


# ---------- Timeline helpers you already use ----------

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
                    StockLedgerEntry.posting_time <= before_dt,   # inclusive
                ),
            ),
            StockLedgerEntry.is_cancelled == False,  # noqa: E712
        )
        .order_by(
            StockLedgerEntry.posting_date.desc(),
            StockLedgerEntry.posting_time.desc(),
            StockLedgerEntry.id.desc(),  # tie-breaker
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
