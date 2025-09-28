# application_accounting/engine/amount_sources.py
from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, Iterable

def _D(x) -> Decimal:
    return Decimal(str(x or 0))

def compute_amounts(payload: Dict[str, Any]) -> Dict[str, Decimal]:
    """
    Produces the amounts dictionary consumed by template lines.
    Keys:
      - DOCUMENT_TOTAL
      - DOCUMENT_SUBTOTAL
      - TAX_AMOUNT
      - ROUNDING_ADJUSTMENT
      - AMOUNT_PAID
      - AMOUNT_RECEIVED
      - INVENTORY_PURCHASE_COST
      - INVOICE_RECEIPT_VALUE
      - COST_OF_GOODS_SOLD
    Missing keys default to 0.
    """
    out: Dict[str, Decimal] = {}

    out["DOCUMENT_SUBTOTAL"]   = _D(payload.get("document_subtotal"))
    out["TAX_AMOUNT"]          = _D(payload.get("tax_amount"))
    out["ROUNDING_ADJUSTMENT"] = _D(payload.get("rounding_adjustment"))
    out["DOCUMENT_TOTAL"]      = _D(payload.get("document_total",
                                         out["DOCUMENT_SUBTOTAL"] + out["TAX_AMOUNT"] + out["ROUNDING_ADJUSTMENT"]))

    out["AMOUNT_PAID"]         = _D(payload.get("amount_paid"))
    out["AMOUNT_RECEIVED"]     = _D(payload.get("amount_received"))

    # Purchases
    if "inventory_purchase_cost" in payload:
        out["INVENTORY_PURCHASE_COST"] = _D(payload.get("inventory_purchase_cost"))
    else:
        # Derive from lines if provided
        total = Decimal("0")
        for ln in payload.get("receipt_lines", []):
            qty = _D(ln.get("accepted_qty"))
            rate = _D(ln.get("unit_price"))
            total += qty * rate
        out["INVENTORY_PURCHASE_COST"] = total

    out["INVOICE_RECEIPT_VALUE"] = _D(payload.get("invoice_receipt_value"))

    # Sales COGS — for SI update_stock or Delivery Note; the caller should pass it
    out["COST_OF_GOODS_SOLD"] = _D(payload.get("cogs_total"))

    return out
