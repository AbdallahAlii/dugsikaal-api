# application_stock/engine/validators.py
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone   # ← add timezone
from typing import Optional

from sqlalchemy import select, exists
from config.database import db
from app.application_stock.stock_models import Warehouse
from app.common.models.base import StatusEnum
from app.application_stock.engine.errors import StockValidationError

MAX_FUTURE_DAYS = 30


def _to_aware_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""
    if dt.tzinfo is None:
        # assume incoming naive timestamps are already UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_item(item_id: int) -> None:
    from app.application_nventory.inventory_models import Item  # adjust path if needed
    if not db.session.execute(select(exists().where(Item.id == item_id))).scalar():
        raise StockValidationError(f"Item {item_id} does not exist.")


def validate_warehouse_is_leaf(company_id: int, branch_id: int, warehouse_id: int) -> None:
    W = Warehouse
    child_exists = db.session.execute(
        select(exists().where(W.parent_warehouse_id == warehouse_id))
    ).scalar()
    wh = db.session.execute(
        select(W).where(
            W.id == warehouse_id,
            W.company_id == company_id,
            W.branch_id == branch_id,
            W.status == StatusEnum.ACTIVE,
        )
    ).scalar_one_or_none()
    if not wh or child_exists:
        raise StockValidationError(f"Warehouse {warehouse_id} is not a transactional (leaf) warehouse.")


def validate_qty(qty: Decimal, *, allow_zero: bool = False, allow_negative: bool = False) -> Decimal:
    try:
        q = Decimal(str(qty))
    except (ValueError, InvalidOperation):
        raise StockValidationError("Invalid quantity.")
    if not allow_zero and q == 0:
        raise StockValidationError("Quantity cannot be zero.")
    if not allow_negative and q < 0:
        raise StockValidationError("Negative quantity not allowed.")
    return q


def validate_rate(rate: Optional[Decimal]) -> Optional[Decimal]:
    if rate is None:
        return None
    try:
        r = Decimal(str(rate))
    except (ValueError, InvalidOperation):
        raise StockValidationError("Invalid rate.")
    if r < 0:
        raise StockValidationError("Negative rate not allowed.")
    return r


def validate_posting_dt(posting_dt: datetime, doc_dt: Optional[datetime] = None) -> None:
    # compare as UTC-aware
    now_utc = datetime.now(timezone.utc)
    posting_utc = _to_aware_utc(posting_dt)
    if posting_utc > now_utc + timedelta(days=MAX_FUTURE_DAYS):
        raise StockValidationError("Posting date too far in future.")
    if doc_dt:
        doc_utc = _to_aware_utc(doc_dt)
        if posting_utc < doc_utc:
            raise StockValidationError("Posting date before document date.")
