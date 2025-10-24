# # #
# # # # app/application_stock/engine/sle_writer.py
#
# # # # app/application_stock/engine/sle_writer.py
# from __future__ import annotations
#
# import logging
# from datetime import datetime, timedelta
# from decimal import Decimal
# from typing import Optional
#
# from sqlalchemy.orm import Session
#
# from app.common.generate_code.service import generate_next_code
# from app.application_stock.stock_models import StockLedgerEntry, DocumentType
# from app.application_stock.engine.types import SLEIntent, AdjustmentType
# from app.application_stock.engine import validators as VAL
# from app.application_stock.engine import selectors as SEL
# from app.application_stock.engine.errors import StockOperationError, StockValidationError
# from app.application_stock.engine.valuation import moving_average as ma
# from app.application_stock.engine.posting_clock import resolve_posting_dt
#
# # NEW: to resolve base_uom_id when meta doesn't include it
# from app.application_nventory.inventory_models import Item
#
# logger = logging.getLogger(__name__)
#
#
# def _validate_item(s: Session, item_id: int) -> None:
#     try:
#         return VAL.validate_item(s, item_id)
#     except TypeError:
#         return VAL.validate_item(item_id)
#
#
# def _validate_wh_leaf(s: Session, company_id: int, branch_id: int, warehouse_id: int) -> None:
#     try:
#         return VAL.validate_warehouse_is_leaf(s, company_id, branch_id, warehouse_id)
#     except TypeError:
#         return VAL.validate_warehouse_is_leaf(company_id, branch_id, warehouse_id)
#
#
# def _validate_posting_dt(posting_dt: datetime) -> None:
#     return VAL.validate_posting_dt(posting_dt)
#
#
# def _validate_rate_non_negative(name: str, val: Optional[Decimal]) -> Optional[Decimal]:
#     """FIX: guard against negative rates sneaking in from dirty data."""
#     if val is None:
#         return None
#     if isinstance(val, Decimal) and val < 0:
#         raise StockValidationError(f"{name} cannot be negative: {val}")
#     return val
#
#
# def _validate_rate(val: Optional[Decimal]) -> Optional[Decimal]:
#     rv = VAL.validate_rate(val)
#     return _validate_rate_non_negative("Rate", rv)
#
#
# def _last_sle_before_dt(
#         s: Session, company_id: int, item_id: int, warehouse_id: int, posting_dt: datetime
# ):
#     # selectors may or may not accept session
#     try:
#         return SEL.get_last_sle_before_dt(s, company_id, item_id, warehouse_id, posting_dt)
#     except TypeError:
#         return SEL.get_last_sle_before_dt(company_id, item_id, warehouse_id, posting_dt)
#
#
# def _gen_sle_code(s: Session, company_id: int, branch_id: int) -> str:
#     return generate_next_code(session=s, prefix="SL", company_id=company_id, branch_id=branch_id)
#
#
# def append_sle(
#         s: Session,
#         intent: SLEIntent,
#         *,
#         valuation_method: str = "moving_average",
#         created_at_hint: Optional[datetime] = None,
#         tz_hint=None,
#         batch_index: int = 0,
# ) -> StockLedgerEntry:
#     """
#     Append one immutable SLE row.
#
#     FIXES:
#     - Properly handles RECONCILIATION adjustments (bypasses stock validation)
#     - Uses resolve_posting_dt with treat_midnight_as_date=True to avoid 00:00:00 collisions.
#     - Adds microsecond bump via `batch_index` so multiple lines in one submit keep strict order.
#     - Enforces non-negative rates.
#     - ALWAYS stores quantities in Base UOM; records txn UOM/qty for audit if provided.
#     """
#     logger.info("append_sle: Starting with intent: %s", intent)
#
#     _validate_item(s, intent.item_id)
#     _validate_wh_leaf(s, intent.company_id, intent.branch_id, intent.warehouse_id)
#
#     resolved_posting_dt = resolve_posting_dt(
#         intent.posting_dt,
#         created_at=created_at_hint,
#         tz=tz_hint,
#         treat_midnight_as_date=True,  # FIX: upgrade midnight 'datetimes' to real times
#         bump_usec=batch_index,  # FIX: deterministic µs bump for ordering
#     )
#     logger.info("append_sle: Resolved posting_dt: %s (timezone: %s)", resolved_posting_dt, resolved_posting_dt.tzinfo)
#     _validate_posting_dt(resolved_posting_dt)
#
#     in_rate = _validate_rate(intent.incoming_rate)
#     out_rate = _validate_rate(intent.outgoing_rate)
#     logger.info("append_sle: Validated rates - incoming: %s, outgoing: %s", in_rate, out_rate)
#
#     # Resolve doc_type_id if needed
#     # Pull txn-UOM metadata (optional)
#     meta = getattr(intent, "meta", {}) or {}
#     if intent.doc_type_id == 0 and getattr(intent, "meta", None) and "doc_type_code" in intent.meta:
#         dt_code = intent.meta["doc_type_code"]
#         dt = s.query(DocumentType).filter_by(code=dt_code).first()
#         if not dt:
#             raise StockOperationError(f"Unknown DocumentType code: {dt_code}")
#         doc_type_id = dt.id
#     else:
#         doc_type_id = intent.doc_type_id
#
#     # Pull txn-UOM metadata (optional)
#     txn_uom_id = meta.get("txn_uom_id")
#     txn_qty_raw = meta.get("txn_qty")
#     base_uom_id = meta.get("base_uom_id")
#
#     # Fallback resolve base_uom_id from Item if not provided
#     if not base_uom_id:
#         it = s.get(Item, intent.item_id)
#         base_uom_id = int(getattr(it, "base_uom_id")) if it and it.base_uom_id else None
#     if not base_uom_id:
#         raise StockOperationError("Item base_uom_id is required to write SLE.")
#
#     # Normalize transaction qty (audit only)
#     txn_qty = None
#     if txn_qty_raw is not None:
#         txn_qty = Decimal(str(txn_qty_raw))
#
#     # Previous state for valuation math - use resolved_posting_dt
#     prev = _last_sle_before_dt(s, intent.company_id, intent.item_id, intent.warehouse_id, resolved_posting_dt)
#     prev_qty = prev.qty_after_transaction if prev and prev.qty_after_transaction is not None else Decimal("0")
#     prev_rate = prev.valuation_rate if prev else Decimal("0")
#     logger.info("append_sle: Previous SLE - qty: %s, rate: %s", prev_qty, prev_rate)
#
#     # 🚨 CRITICAL FIX: Handle RECONCILIATION differently - bypass stock validation
#     if intent.adjustment_type == AdjustmentType.RECONCILIATION:
#         logger.info("append_sle: Processing RECONCILIATION adjustment")
#
#         # For reconciliation, use the counted quantity from meta
#         counted_qty_base = Decimal(meta.get("counted_qty_base", "0"))
#         valuation_rate_used = Decimal(meta.get("valuation_rate_used", "0"))
#
#         qty_before = prev_qty
#         qty_after = counted_qty_base  # 🎯 This is the key fix!
#         rate_after = valuation_rate_used
#         value_diff = intent.stock_value_difference
#
#         logger.info(f"Reconciliation - counted: {counted_qty_base}, prev: {prev_qty}, qty_after: {qty_after}")
#
#     else:
#         # 🚨 CRITICAL FIX: Stock validation only for NON-reconciliation adjustments
#         # Prevent negative stock quantities on issues (but NOT for reconciliation)
#         if intent.actual_qty < 0 and abs(intent.actual_qty) > prev_qty:
#             raise StockValidationError(
#                 f"Insufficient stock for issue. Available: {prev_qty}, Requested: {abs(intent.actual_qty)}"
#             )
#
#         # Normal stock movement logic
#         if intent.actual_qty > 0 and in_rate is not None:
#             # Receipt
#             logger.info("append_sle: Processing receipt - qty: %s, rate: %s", intent.actual_qty, in_rate)
#             qty_after, rate_after, value_diff = ma.apply_receipt(prev_qty, prev_rate, intent.actual_qty, in_rate)
#             logger.info("append_sle: After receipt - qty_after: %s, rate_after: %s, value_diff: %s", qty_after,
#                         rate_after, value_diff)
#         elif intent.actual_qty < 0:
#             # Issue
#             logger.info("append_sle: Processing issue - qty: %s", intent.actual_qty)
#             qty_after, rate_after, value_diff = ma.apply_issue(prev_qty, prev_rate, -intent.actual_qty)
#             out_rate_final = prev_rate if out_rate is None else out_rate
#             logger.info("append_sle: After issue - qty_after: %s, rate_after: %s, value_diff: %s", qty_after,
#                         rate_after, value_diff)
#         else:
#             # Zero-qty valuation change (revaluation)
#             logger.info("append_sle: Processing zero-qty revaluation - value_diff: %s", intent.stock_value_difference)
#             qty_after, rate_after, value_diff = ma.apply_zero_qty_revaluation(prev_qty, prev_rate,
#                                                                               intent.stock_value_difference)
#             logger.info("append_sle: After revaluation - qty_after: %s, rate_after: %s, value_diff: %s", qty_after,
#                         rate_after, value_diff)
#
#     sle = StockLedgerEntry(
#         company_id=intent.company_id,
#         branch_id=intent.branch_id,
#         item_id=intent.item_id,
#         warehouse_id=intent.warehouse_id,
#         code=_gen_sle_code(s, intent.company_id, intent.branch_id),
#         posting_date=resolved_posting_dt.date(),
#         posting_time=resolved_posting_dt,
#
#         # ✔ base units only:
#         actual_qty=intent.actual_qty,
#         incoming_rate=in_rate,
#         outgoing_rate=out_rate_final if 'out_rate_final' in locals() else out_rate,
#         valuation_rate=rate_after,
#
#         stock_value_difference=value_diff if intent.actual_qty != 0 else intent.stock_value_difference,
#
#         doc_type_id=doc_type_id,
#         doc_id=intent.doc_id,
#         doc_row_id=intent.doc_row_id,
#
#         qty_before_transaction=qty_before,
#         qty_after_transaction=qty_after,
#
#         # NEW: UOM tracking (audit fields)
#         base_uom_id=int(base_uom_id),
#         transaction_uom_id=int(txn_uom_id) if txn_uom_id else None,
#         transaction_quantity=txn_qty,
#
#         is_cancelled=False,
#         is_reversal=(intent.adjustment_type == AdjustmentType.REVERSAL),
#         reversed_sle_id=None,
#         adjustment_type=intent.adjustment_type,
#     )
#
#     logger.info("append_sle: Created SLE object - actual_qty: %s, posting_time: %s", sle.actual_qty, sle.posting_time)
#     s.add(sle)
#     logger.info("append_sle: SLE added to session - ID: %s, actual_qty: %s", sle.id, sle.actual_qty)
#     return sle
#
#
# def cancel_sle(s: Session, original: StockLedgerEntry) -> StockLedgerEntry:
#     """Write a system-generated reversal row and mark original as cancelled."""
#     logger.info("cancel_sle: Starting for SLE ID %s", original.id)
#
#     original.is_cancelled = True
#
#     # ensure reversal sorts AFTER the original for the same second
#     reversal_time = original.posting_time + timedelta(microseconds=1)
#     logger.info("cancel_sle: Reversal time: %s", reversal_time)
#
#     reversal = StockLedgerEntry(
#         company_id=original.company_id,
#         branch_id=original.branch_id,
#         item_id=original.item_id,
#         warehouse_id=original.warehouse_id,
#         code=_gen_sle_code(s, original.company_id, original.branch_id),
#         posting_date=reversal_time.date(),
#         posting_time=reversal_time,
#
#         # negate base qty; audit prices stay validated non-negative
#         actual_qty=-original.actual_qty,
#         incoming_rate=_validate_rate_non_negative("incoming_rate", original.incoming_rate),
#         outgoing_rate=_validate_rate_non_negative("outgoing_rate", original.outgoing_rate),
#         valuation_rate=_validate_rate_non_negative("valuation_rate", original.valuation_rate),
#
#         stock_value_difference=-(original.stock_value_difference or Decimal("0")),
#
#         doc_type_id=original.doc_type_id,
#         doc_id=original.doc_id,
#         doc_row_id=original.doc_row_id,
#
#         qty_before_transaction=original.qty_after_transaction,
#         qty_after_transaction=original.qty_before_transaction,
#
#         # carry forward UOM audit fields so NOT NULL base_uom_id is satisfied
#         base_uom_id=original.base_uom_id,
#         transaction_uom_id=original.transaction_uom_id,
#         transaction_quantity=(-original.transaction_quantity if original.transaction_quantity is not None else None),
#
#         is_cancelled=False,
#         is_reversal=True,
#         reversed_sle_id=original.id,
#         adjustment_type=original.adjustment_type,
#     )
#
#     logger.info("cancel_sle: Created reversal SLE - actual_qty: %s", reversal.actual_qty)
#     s.add(reversal)
#     logger.info("cancel_sle: Reversal SLE added to session - ID: %s", reversal.id)
#     return reversal
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
        s: Session, company_id: int, item_id: int, warehouse_id: int, posting_dt: datetime
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
    logger.info("append_sle: Resolved posting_dt: %s (timezone: %s)", resolved_posting_dt, resolved_posting_dt.tzinfo)
    _validate_posting_dt(resolved_posting_dt)

    # Validate rates
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

    prev = _last_sle_before_dt(s, intent.company_id, intent.item_id, intent.warehouse_id, resolved_posting_dt)
    prev_qty = prev.qty_after_transaction if prev and prev.qty_after_transaction is not None else Decimal("0")
    prev_rate = prev.valuation_rate if prev else Decimal("0")
    logger.info("append_sle: Previous SLE - qty: %s, rate: %s", prev_qty, prev_rate)

    # Stock movement logic: Receipts, Issues, or Revaluation
    if intent.actual_qty > 0 and in_rate is not None:
        qty_after, rate_after, value_diff = ma.apply_receipt(prev_qty, prev_rate, intent.actual_qty, in_rate)
        logger.info("append_sle: After receipt - qty_after: %s, rate_after: %s, value_diff: %s", qty_after,
                    rate_after, value_diff)
    elif intent.actual_qty < 0:
        qty_after, rate_after, value_diff = ma.apply_issue(prev_qty, prev_rate, -intent.actual_qty)
        out_rate_final = prev_rate if out_rate is None else out_rate
        logger.info("append_sle: After issue - qty_after: %s, rate_after: %s, value_diff: %s", qty_after,
                    rate_after, value_diff)
    else:
        qty_after, rate_after, value_diff = ma.apply_zero_qty_revaluation(prev_qty, prev_rate,
                                                                          intent.stock_value_difference)

    # Create SLE entry
    sle = StockLedgerEntry(
        company_id=intent.company_id,
        branch_id=intent.branch_id,
        item_id=intent.item_id,
        warehouse_id=intent.warehouse_id,
        code=_gen_sle_code(s, intent.company_id, intent.branch_id),
        posting_date=resolved_posting_dt.date(),
        posting_time=resolved_posting_dt,
        actual_qty=intent.actual_qty,
        incoming_rate=in_rate,
        outgoing_rate=out_rate_final if 'out_rate_final' in locals() else out_rate,
        valuation_rate=rate_after,
        stock_value_difference=value_diff if intent.actual_qty != 0 else intent.stock_value_difference,
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
        transaction_quantity=(-original.transaction_quantity if original.transaction_quantity is not None else None),

        is_cancelled=False,
        is_reversal=True,
        reversed_sle_id=original.id,
        adjustment_type=original.adjustment_type,
    )

    s.add(reversal)
    return reversal
