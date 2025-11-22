
# app/application_stock/engine/sle_writer.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.common.generate_code.service import generate_next_code
from app.application_stock.stock_models import StockLedgerEntry, DocumentType
from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_stock.engine import validators as VAL
from app.application_stock.engine import selectors as SEL
from app.application_stock.engine.errors import StockOperationError, StockValidationError
from app.application_stock.engine.valuation import moving_average as ma
from app.application_stock.engine.posting_clock import resolve_posting_dt

# NEW: to resolve base_uom_id when meta doesn't include it
from app.application_nventory.inventory_models import Item

logger = logging.getLogger(__name__)


def _validate_item(s: Session, item_id: int) -> None:
    try:
        return VAL.validate_item(s, item_id)
    except TypeError:
        return VAL.validate_item(item_id)


def _validate_wh_leaf(s: Session, company_id: int, branch_id: int, warehouse_id: int) -> None:
    try:
        return VAL.validate_warehouse_is_leaf(s, company_id, branch_id, warehouse_id)
    except TypeError:
        return VAL.validate_warehouse_is_leaf(company_id, branch_id, warehouse_id)


def _validate_posting_dt(posting_dt: datetime) -> None:
    return VAL.validate_posting_dt(posting_dt)


def _validate_rate_non_negative(name: str, val: Optional[Decimal]) -> Optional[Decimal]:
    """FIX: guard against negative rates sneaking in from dirty data."""
    if val is None:
        return None
    if isinstance(val, Decimal) and val < 0:
        raise StockValidationError(f"{name} cannot be negative: {val}")
    return val


def _validate_rate(val: Optional[Decimal]) -> Optional[Decimal]:
    rv = VAL.validate_rate(val)
    return _validate_rate_non_negative("Rate", rv)


def _last_sle_before_dt(
    s: Session,
    company_id: int,
    item_id: int,
    warehouse_id: int,
    posting_dt: datetime,
):
    try:
        return SEL.get_last_sle_before_dt(s, company_id, item_id, warehouse_id, posting_dt)
    except TypeError:
        return SEL.get_last_sle_before_dt(company_id, item_id, warehouse_id, posting_dt)


def _gen_sle_code(s: Session, company_id: int, branch_id: int) -> str:
    return generate_next_code(session=s, prefix="SL", company_id=company_id, branch_id=branch_id)


def append_sle(
    s: Session,
    intent: SLEIntent,
    *,
    valuation_method: str = "moving_average",
    created_at_hint: Optional[datetime] = None,
    tz_hint=None,
    batch_index: int = 0,
) -> StockLedgerEntry:
    """
    Append one immutable SLE row.

    NORMAL DOCS (no change from previous behaviour):
      - actual_qty > 0 AND incoming_rate is not None -> receipt (moving average)
      - actual_qty < 0 -> issue
      - actual_qty == 0 AND stock_value_difference -> pure revaluation

    STOCK RECONCILIATION (NEW, but isolated):
      - adjustment_type == RECONCILIATION
      - actual_qty != 0
      - stock_value_difference is not None

      In this mode we:
        * move quantity by actual_qty
        * apply stock_value_difference explicitly
        * recompute valuation_rate so that:
              new_value = prev_value + stock_value_difference
              new_qty   = prev_qty  + actual_qty
              new_rate  = new_value / new_qty (if new_qty != 0)
    """
    logger.info("append_sle: Starting with intent: %s", intent)

    _validate_item(s, intent.item_id)
    _validate_wh_leaf(s, intent.company_id, intent.branch_id, intent.warehouse_id)

    # Resolve posting datetime considering time zone
    resolved_posting_dt = resolve_posting_dt(
        intent.posting_dt,
        created_at=created_at_hint,
        tz=tz_hint,
        treat_midnight_as_date=True,
        bump_usec=batch_index,  # Microsecond bump for strict order
    )
    logger.info(
        "append_sle: Resolved posting_dt: %s (timezone: %s)",
        resolved_posting_dt,
        resolved_posting_dt.tzinfo,
    )
    _validate_posting_dt(resolved_posting_dt)

    # Validate rates (may be None)
    in_rate = _validate_rate(intent.incoming_rate)
    out_rate = _validate_rate(intent.outgoing_rate)
    logger.info("append_sle: Validated rates - incoming: %s, outgoing: %s", in_rate, out_rate)

    # Resolve doc_type_id if needed
    meta = getattr(intent, "meta", {}) or {}
    if intent.doc_type_id == 0 and "doc_type_code" in meta:
        dt_code = meta["doc_type_code"]
        dt = s.query(DocumentType).filter_by(code=dt_code).first()
        if not dt:
            raise StockOperationError(f"Unknown DocumentType code: {dt_code}")
        doc_type_id = dt.id
    else:
        doc_type_id = intent.doc_type_id

    # Resolve base_uom_id from Item if not provided
    base_uom_id = meta.get("base_uom_id")
    if not base_uom_id:
        it = s.get(Item, intent.item_id)
        base_uom_id = int(getattr(it, "base_uom_id")) if it and it.base_uom_id else None
    if not base_uom_id:
        raise StockOperationError("Item base_uom_id is required to write SLE.")

    txn_qty_raw = meta.get("txn_qty")
    txn_qty = Decimal(str(txn_qty_raw)) if txn_qty_raw else None

    prev = _last_sle_before_dt(
        s,
        intent.company_id,
        intent.item_id,
        intent.warehouse_id,
        resolved_posting_dt,
    )
    prev_qty = prev.qty_after_transaction if prev and prev.qty_after_transaction is not None else Decimal("0")
    prev_rate = prev.valuation_rate if prev and prev.valuation_rate is not None else Decimal("0")
    logger.info("append_sle: Previous SLE - qty: %s, rate: %s", prev_qty, prev_rate)

    # -------- Stock movement / valuation logic --------
    qty_after: Decimal
    rate_after: Decimal
    value_diff: Decimal

    in_rate_final = in_rate
    out_rate_final = out_rate

    # Detect reconciliation mode (ONLY affects Stock Reconciliation)
    recon_mode = (
        intent.adjustment_type == AdjustmentType.RECONCILIATION
        and intent.actual_qty is not None
        and intent.actual_qty != 0
        and intent.stock_value_difference is not None
    )

    if recon_mode:
        # 🔄 Reconciliation: move quantity AND apply explicit stock_value_difference
        svd = intent.stock_value_difference
        prev_value = prev_qty * prev_rate
        new_qty = prev_qty + intent.actual_qty
        new_value = prev_value + svd

        qty_after = new_qty
        if new_qty != 0:
            rate_after = new_value / new_qty
        else:
            # No stock left, keep old rate (or set to 0; both are acceptable)
            rate_after = prev_rate

        value_diff = svd

        logger.info(
            "append_sle[RECON]: prev_qty=%s prev_rate=%s prev_value=%s | "
            "actual_qty=%s stock_value_difference=%s | new_qty=%s new_value=%s new_rate=%s",
            prev_qty,
            prev_rate,
            prev_value,
            intent.actual_qty,
            svd,
            qty_after,
            new_value,
            rate_after,
        )

    else:
        # NORMAL BEHAVIOUR (unchanged for Stock Entry, Purchase, Sales, etc.)

        # Receipt: qty > 0 and we have an incoming rate
        if intent.actual_qty > 0 and in_rate is not None:
            qty_after, rate_after, value_diff = ma.apply_receipt(
                prev_qty,
                prev_rate,
                intent.actual_qty,
                in_rate,
            )
            logger.info(
                "append_sle: After receipt - qty_after: %s, rate_after: %s, value_diff: %s",
                qty_after,
                rate_after,
                value_diff,
            )

        # Issue: qty < 0
        elif intent.actual_qty < 0:
            qty_after, rate_after, value_diff = ma.apply_issue(
                prev_qty,
                prev_rate,
                -intent.actual_qty,
            )
            # For issues, if no explicit outgoing_rate, we assume prev_rate
            if out_rate_final is None:
                out_rate_final = prev_rate
            logger.info(
                "append_sle: After issue - qty_after: %s, rate_after: %s, value_diff: %s",
                qty_after,
                rate_after,
                value_diff,
            )

        # Zero-qty revaluation
        else:
            qty_after, rate_after, value_diff = ma.apply_zero_qty_revaluation(
                prev_qty,
                prev_rate,
                intent.stock_value_difference or Decimal("0"),
            )
            logger.info(
                "append_sle: After zero-qty revaluation - qty_after: %s, rate_after: %s, value_diff: %s",
                qty_after,
                rate_after,
                value_diff,
            )

    # -------- Create SLE entry --------
    sle = StockLedgerEntry(
        company_id=intent.company_id,
        branch_id=intent.branch_id,
        item_id=intent.item_id,
        warehouse_id=intent.warehouse_id,
        code=_gen_sle_code(s, intent.company_id, intent.branch_id),
        posting_date=resolved_posting_dt.date(),
        posting_time=resolved_posting_dt,
        actual_qty=intent.actual_qty,
        incoming_rate=in_rate_final,
        outgoing_rate=out_rate_final,
        valuation_rate=rate_after,
        # For non-zero qty we use the calculated value_diff,
        # for zero-qty revaluation we use the explicit stock_value_difference.
        stock_value_difference=(
            value_diff if intent.actual_qty != 0 else (intent.stock_value_difference or Decimal("0"))
        ),
        doc_type_id=doc_type_id,
        doc_id=intent.doc_id,
        doc_row_id=intent.doc_row_id,
        qty_before_transaction=prev_qty,
        qty_after_transaction=qty_after,
        base_uom_id=int(base_uom_id),
        transaction_uom_id=int(meta.get("txn_uom_id")) if meta.get("txn_uom_id") else None,
        transaction_quantity=txn_qty,
        is_cancelled=False,
        is_reversal=(intent.adjustment_type == AdjustmentType.REVERSAL),
        reversed_sle_id=None,
        adjustment_type=intent.adjustment_type,
    )

    s.add(sle)
    return sle


def cancel_sle(s: Session, original: StockLedgerEntry) -> StockLedgerEntry:
    """Write a system-generated reversal row and mark original as cancelled."""
    logger.info("cancel_sle: Starting for SLE ID %s", original.id)

    original.is_cancelled = True

    # Ensure reversal sorts AFTER the original for the same second
    reversal_time = original.posting_time + timedelta(microseconds=1)
    logger.info("cancel_sle: Reversal time: %s", reversal_time)

    reversal = StockLedgerEntry(
        company_id=original.company_id,
        branch_id=original.branch_id,
        item_id=original.item_id,
        warehouse_id=original.warehouse_id,
        code=_gen_sle_code(s, original.company_id, original.branch_id),
        posting_date=reversal_time.date(),
        posting_time=reversal_time,

        # Negate base qty and other fields for reversal
        actual_qty=-original.actual_qty,
        incoming_rate=_validate_rate_non_negative("incoming_rate", original.incoming_rate),
        outgoing_rate=_validate_rate_non_negative("outgoing_rate", original.outgoing_rate),
        valuation_rate=_validate_rate_non_negative("valuation_rate", original.valuation_rate),

        stock_value_difference=-(original.stock_value_difference or Decimal("0")),

        doc_type_id=original.doc_type_id,
        doc_id=original.doc_id,
        doc_row_id=original.doc_row_id,

        qty_before_transaction=original.qty_after_transaction,
        qty_after_transaction=original.qty_before_transaction,

        # Carry forward UOM audit fields so NOT NULL base_uom_id is satisfied
        base_uom_id=original.base_uom_id,
        transaction_uom_id=original.transaction_uom_id,
        transaction_quantity=(
            -original.transaction_quantity if original.transaction_quantity is not None else None
        ),

        is_cancelled=False,
        is_reversal=True,
        reversed_sle_id=original.id,
        adjustment_type=original.adjustment_type,
    )

    s.add(reversal)
    return reversal
