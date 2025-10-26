# app/application_stock/engine/handlers/sales.py
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple, DefaultDict
from collections import defaultdict

from sqlalchemy.orm import Session

from app.application_stock.engine.types import SLEIntent, AdjustmentType
from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
from app.application_nventory.inventory_models import Item
from config.database import db

logger = logging.getLogger(__name__)

__all__ = [
    # Stock (SLE)
    "build_intents_for_delivery_note",
    "build_intents_for_sales_invoice_stock",
    "sum_cogs_from_intents",

    # Finance contexts for GL templates
    "build_gl_context_for_sales_invoice_finance_only",
    "build_gl_context_for_sales_invoice_with_stock",
    "build_gl_context_for_delivery_note",
]

# ---------------------------------------------------------------------------
# Helpers (same pattern as purchase.py)
# ---------------------------------------------------------------------------

def _to_decimal(val: Any, *, field: str, default: Optional[Decimal] = None) -> Decimal:
    if val is None:
        if default is not None:
            return default
        raise ValueError(f"Missing required decimal value for '{field}'")
    try:
        return Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError) as e:
        logger.error(f"Decimal conversion failed for '{field}': {val!r} - {e}")
        raise ValueError(f"Invalid decimal value for '{field}': {val!r}")

def _coerce_int(val: Any, *, field: str) -> int:
    if val is None:
        raise ValueError(f"Missing required integer value for '{field}'")
    try:
        return int(val)
    except (TypeError, ValueError) as e:
        logger.error(f"Integer conversion failed for '{field}': {val!r} - {e}")
        raise ValueError(f"Invalid integer for '{field}': {val!r}")

def _get_base_uom_id(session: Session, item_id: int) -> int:
    try:
        item = session.get(Item, item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        if not item.base_uom_id:
            raise ValueError(f"Item {item_id} has no base UOM configured")
        return int(item.base_uom_id)
    except Exception as e:
        logger.error(f"Failed to fetch base UOM for item {item_id}: {e}")
        raise ValueError(f"Cannot determine base UOM for item {item_id}: {e}")

def _to_base_qty_only(
    *,
    session: Session,
    item_id: int,
    qty: Decimal,
    uom_id: Optional[int],
    maybe_base_uom_id: Optional[int],
) -> Tuple[Decimal, int]:
    """
    Convert quantity to base UOM if needed (rate untouched).
    """
    if uom_id is None:
        base_uom_id = maybe_base_uom_id or _get_base_uom_id(session, item_id)
        return qty, base_uom_id

    uom_id = _coerce_int(uom_id, field="uom_id")
    base_uom_id = _coerce_int(maybe_base_uom_id, field="base_uom_id") if maybe_base_uom_id else _get_base_uom_id(session, item_id)

    if uom_id == base_uom_id:
        return qty, base_uom_id

    try:
        base_qty_float, _ = to_base_qty(
            qty=qty, item_id=item_id, uom_id=uom_id, base_uom_id=base_uom_id, strict=True
        )
        return Decimal(str(base_qty_float)), base_uom_id
    except UOMFactorMissing as e:
        raise ValueError(
            f"Missing UOM conversion for item_id={item_id}, uom_id={uom_id}, base_uom_id={base_uom_id}"
        ) from e

# ---------------------------------------------------------------------------
# SLE Builders (Delivery Note & Sales Invoice with Update Stock)
# ---------------------------------------------------------------------------

def build_intents_for_delivery_note(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    is_return: bool,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLE intents for a Delivery Note.
    Required per line: item_id, warehouse_id, delivered_qty
    Optional per line: uom_id, base_uom_id, doc_row_id
    Sign:
      - is_return=False  -> issue  (actual_qty negative)
      - is_return=True   -> receipt(actual_qty positive)
    """
    s = session or db.session
    intents: List[SLEIntent] = []
    from app.application_stock.engine import selectors as SEL

    for idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            warehouse_id = _coerce_int(line["warehouse_id"], field="warehouse_id")
            qty_u = _to_decimal(line.get("delivered_qty"), field="delivered_qty")
            uom_id = line.get("uom_id")
            base_uom_id = line.get("base_uom_id")
            doc_row_id = line.get("doc_row_id")

            base_qty, base_uom_id = _to_base_qty_only(
                session=s, item_id=item_id, qty=abs(qty_u), uom_id=uom_id, maybe_base_uom_id=base_uom_id
            )
            sign = Decimal("1") if is_return else Decimal("-1")
            actual_qty = sign * base_qty

            rate = SEL.get_current_valuation_rate(s, company_id, item_id, warehouse_id) or Decimal("0")

            intents.append(SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=actual_qty,
                incoming_rate=rate if is_return else None,
                outgoing_rate=rate if not is_return else None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={"base_uom_id": base_uom_id, "txn_qty": str(qty_u), "source": "DeliveryNote"},
            ))
        except Exception as e:
            logger.error(f"DeliveryNote line {idx} failed: {e} | {line}")
            raise

    return intents


def build_intents_for_sales_invoice_stock(
    *,
    company_id: int,
    branch_id: int,
    posting_dt: datetime,
    doc_type_id: int,
    doc_id: int,
    is_return: bool,
    lines: Iterable[Dict[str, Any]],
    session: Optional[Session] = None,
) -> List[SLEIntent]:
    """
    Build SLE intents for a Sales Invoice when update_stock=True.
    Required per line: item_id, warehouse_id, quantity
    Optional per line: uom_id, base_uom_id, doc_row_id
    Sign:
      - is_return=False  -> issue  (actual_qty negative)
      - is_return=True   -> receipt(actual_qty positive)
    """
    s = session or db.session
    intents: List[SLEIntent] = []
    from app.application_stock.engine import selectors as SEL

    for idx, line in enumerate(lines):
        try:
            item_id = _coerce_int(line["item_id"], field="item_id")
            warehouse_id = _coerce_int(line["warehouse_id"], field="warehouse_id")
            qty_u = _to_decimal(line.get("quantity"), field="quantity")
            uom_id = line.get("uom_id")
            base_uom_id = line.get("base_uom_id")
            doc_row_id = line.get("doc_row_id")

            base_qty, base_uom_id = _to_base_qty_only(
                session=s, item_id=item_id, qty=abs(qty_u), uom_id=uom_id, maybe_base_uom_id=base_uom_id
            )
            sign = Decimal("1") if is_return else Decimal("-1")
            actual_qty = sign * base_qty

            rate = SEL.get_current_valuation_rate(s, company_id, item_id, warehouse_id) or Decimal("0")

            intents.append(SLEIntent(
                company_id=company_id,
                branch_id=branch_id,
                item_id=item_id,
                warehouse_id=warehouse_id,
                posting_dt=posting_dt,
                actual_qty=actual_qty,
                incoming_rate=rate if is_return else None,
                outgoing_rate=rate if not is_return else None,
                stock_value_difference=Decimal("0"),
                doc_type_id=doc_type_id,
                doc_id=doc_id,
                doc_row_id=doc_row_id,
                adjustment_type=AdjustmentType.NORMAL,
                meta={"base_uom_id": base_uom_id, "txn_qty": str(qty_u), "source": "SalesInvoice(update_stock)"},
            ))
        except Exception as e:
            logger.error(f"SalesInvoice(stock) line {idx} failed: {e} | {line}")
            raise

    return intents

# Utility to compute COGS magnitude from SLEs (abs(qty) * rate)
def sum_cogs_from_intents(intents: Iterable[SLEIntent]) -> Decimal:
    total = Decimal("0")
    for it in intents:
        rate = it.incoming_rate if it.incoming_rate is not None else it.outgoing_rate or Decimal("0")
        qty = abs(Decimal(str(it.actual_qty)))
        total += qty * (rate or Decimal("0"))
    return total

# ---------------------------------------------------------------------------
# Finance GL Context Builders (feed TEMPLATE_ITEMS)
# ---------------------------------------------------------------------------

def _aggregate_income_splits(lines: Iterable[Dict[str, Any]]) -> Tuple[DefaultDict[int, Decimal], Decimal]:
    """
    Sum DOCUMENT_SUBTOTAL by income_account_id across lines.
    Each line must have:
      - 'amount' (Decimal)  -> quantity*rate, net before tax
      - 'income_account_id' (int)
    """
    splits: DefaultDict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    subtotal = Decimal("0")
    for idx, line in enumerate(lines):
        amt = _to_decimal(line.get("amount"), field=f"lines[{idx}].amount")
        inc_acc = _coerce_int(line.get("income_account_id"), field=f"lines[{idx}].income_account_id")
        splits[inc_acc] += amt
        subtotal += amt
    return splits, subtotal

def build_gl_context_for_sales_invoice_finance_only(
    *,
    debit_to_account_id: Optional[int],
    vat_account_id: Optional[int],
    total_amount: Any,           # DOCUMENT_TOTAL (sign can be negative for returns)
    vat_amount: Any,             # TAX_AMOUNT (>=0)
    lines: Iterable[Dict[str, Any]],  # needs 'amount' & 'income_account_id'
    discount_amount: Any = Decimal("0"),
    round_off_positive: Any = Decimal("0"),
    round_off_negative: Any = Decimal("0"),
    default_ar_account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Context for SALES_INV_AR (or SALES_RETURN_CREDIT if you select that template).
    Includes multi-income splits and dynamic tax account.
    """
    doc_total = _to_decimal(total_amount, field="total_amount")
    tax_amt = _to_decimal(vat_amount, field="vat_amount", default=Decimal("0"))
    disc_amt = _to_decimal(discount_amount, field="discount_amount", default=Decimal("0"))
    ro_pos = _to_decimal(round_off_positive, field="round_off_positive", default=Decimal("0"))
    ro_neg = _to_decimal(round_off_negative, field="round_off_negative", default=Decimal("0"))

    income_splits, subtotal = _aggregate_income_splits(lines)

    ar_acc = debit_to_account_id or default_ar_account_id
    if not ar_acc:
        raise ValueError("accounts_receivable_account_id is required (provide debit_to_account_id or default_ar_account_id)")

    return {
        # amounts
        "DOCUMENT_TOTAL": doc_total,
        "DOCUMENT_SUBTOTAL": subtotal,
        "TAX_AMOUNT": tax_amt,
        "DISCOUNT_AMOUNT": disc_amt,
        "ROUND_OFF_POSITIVE": ro_pos,
        "ROUND_OFF_NEGATIVE": ro_neg,

        # dynamic accounts
        "accounts_receivable_account_id": int(ar_acc),
        "tax_account_id": int(vat_account_id) if vat_account_id else None,

        # income splits for the posting engine to explode
        "income_splits": {acc: amt for acc, amt in income_splits.items()},
    }

def build_gl_context_for_sales_invoice_with_stock(
    *,
    debit_to_account_id: Optional[int],
    vat_account_id: Optional[int],
    total_amount: Any,
    vat_amount: Any,
    lines: Iterable[Dict[str, Any]],
    cogs_total: Any,                 # positive magnitude
    is_return: bool,
    discount_amount: Any = Decimal("0"),
    round_off_positive: Any = Decimal("0"),
    round_off_negative: Any = Decimal("0"),
    default_ar_account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Context for SALES_INV_WITH_STOCK (or return variant).
    Adds COST_OF_GOODS_SOLD or COGS_REVERSAL bucket.
    """
    base = build_gl_context_for_sales_invoice_finance_only(
        debit_to_account_id=debit_to_account_id,
        vat_account_id=vat_account_id,
        total_amount=total_amount,
        vat_amount=vat_amount,
        lines=lines,
        discount_amount=discount_amount,
        round_off_positive=round_off_positive,
        round_off_negative=round_off_negative,
        default_ar_account_id=default_ar_account_id,
    )
    cogs_val = _to_decimal(cogs_total, field="cogs_total", default=Decimal("0"))
    if not is_return:
        base["COST_OF_GOODS_SOLD"] = cogs_val
    else:
        base["COGS_REVERSAL"] = cogs_val
    return base

def build_gl_context_for_delivery_note(
    *,
    cogs_total: Any,
    is_return: bool,
) -> Dict[str, Any]:
    """
    Context for DN COGS template. Your DN templates encode debit/credit.
    We provide the magnitude and a flag (if your posting service needs it).
    """
    cogs_val = _to_decimal(cogs_total, field="cogs_total", default=Decimal("0"))
    return {"COST_OF_GOODS_SOLD": cogs_val, "IS_RETURN": bool(is_return)}
