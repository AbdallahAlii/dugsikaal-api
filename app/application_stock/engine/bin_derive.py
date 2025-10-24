# # # # # application_stock/engine/bin_derive.py
#
# from __future__ import annotations
#
# import logging
# from decimal import Decimal
# from typing import Optional
# from uuid import uuid4
#
# from sqlalchemy import select
# from sqlalchemy.orm import Session
# from sqlalchemy.inspection import inspect as sqla_inspect
#
# from app.application_stock.stock_models import StockLedgerEntry, Bin
#
# logger = logging.getLogger(__name__)
#
#
# def _make_bin_code(s: Session, item_id: int, warehouse_id: int) -> str:
#     for _ in range(4):
#         code = uuid4().hex[:12]
#         exists = s.execute(
#             select(Bin.id).where(Bin.code == code).limit(1)
#         ).scalar_one_or_none()
#         if not exists:
#             return code
#     return uuid4().hex
#
#
# def _is_generated_column(model, attr_name: str) -> bool:
#     """
#     Returns True if `model.attr_name` is a GENERATED ALWAYS/GENERATED column.
#     Works with SQLAlchemy's Computed() metadata when present.
#     """
#     mapper = sqla_inspect(model)
#     col = mapper.columns.get(attr_name)
#     return bool(getattr(col, "computed", None))
#
#
# def ensure_bin(
#         s: Session,
#         *,
#         company_id: int,
#         item_id: int,
#         warehouse_id: int,
# ) -> Bin:
#     """
#     Get-or-create the Bin row for (company,item,warehouse).
#     Does NOT touch generated columns (e.g., projected_qty, stock_value).
#     """
#     logger.info(f"ensure_bin: Looking for bin for company={company_id}, item={item_id}, wh={warehouse_id}")
#
#     b: Optional[Bin] = s.execute(
#         select(Bin)
#         .where(
#             Bin.company_id == company_id,
#             Bin.item_id == item_id,
#             Bin.warehouse_id == warehouse_id,
#         )
#         .with_for_update()
#     ).scalar_one_or_none()
#
#     if not b:
#         logger.info("ensure_bin: Creating new bin")
#         b = Bin(
#             company_id=company_id,
#             item_id=item_id,
#             warehouse_id=warehouse_id,
#             code=_make_bin_code(s, item_id, warehouse_id),
#             actual_qty=Decimal("0"),
#             reserved_qty=Decimal("0"),
#             ordered_qty=Decimal("0"),
#             valuation_rate=Decimal("0"),
#             # DO NOT set generated columns here
#             # projected_qty → generated
#             # stock_value   → generated
#         )
#         s.add(b)
#         s.flush([b])
#         logger.info(f"ensure_bin: Created new bin with ID {b.id}")
#     else:
#         logger.info(f"ensure_bin: Found existing bin with ID {b.id}")
#
#     return b
#
#
# def derive_bin(
#         s: Session,
#         company_id: int,
#         item_id: int,
#         warehouse_id: int,
# ) -> Bin:
#     """
#     Set Bin to the state of the latest non-cancelled SLE for this (company,item,warehouse).
#     """
#     logger.info(f"derive_bin: Starting for company={company_id}, item={item_id}, wh={warehouse_id}")
#
#     last: Optional[StockLedgerEntry] = s.execute(
#         select(StockLedgerEntry)
#         .where(
#             StockLedgerEntry.company_id == company_id,
#             StockLedgerEntry.item_id == item_id,
#             StockLedgerEntry.warehouse_id == warehouse_id,
#             StockLedgerEntry.is_cancelled == False,
#         )
#         .order_by(
#             StockLedgerEntry.posting_date.desc(),
#             StockLedgerEntry.posting_time.desc(),
#             StockLedgerEntry.id.desc(),
#         )
#         .limit(1)
#     ).scalar_one_or_none()
#
#     b = ensure_bin(s, company_id=company_id, item_id=item_id, warehouse_id=warehouse_id)
#
#     # Always safe to assign these:
#     if last:
#         logger.info(
#             f"derive_bin: Found last non-cancelled SLE (ID {last.id}) with qty {last.qty_after_transaction} and rate {last.valuation_rate}")
#         b.actual_qty = last.qty_after_transaction or Decimal("0")
#         b.valuation_rate = last.valuation_rate or Decimal("0")
#     else:
#         logger.info("derive_bin: No non-cancelled SLEs found. Setting to zero.")
#         b.actual_qty = Decimal("0")
#         b.valuation_rate = Decimal("0")
#
#     # Detect and DO NOT touch generated columns
#     proj_is_generated = _is_generated_column(Bin, "projected_qty")
#     stock_is_generated = _is_generated_column(Bin, "stock_value")
#
#     # If your schema does NOT mark them as generated, we can keep them consistent.
#     # If they ARE generated, skip assignment so Postgres computes them.
#     if not proj_is_generated and hasattr(Bin, "projected_qty"):
#         b.projected_qty = (b.actual_qty or Decimal("0")) \
#                           + (b.ordered_qty or Decimal("0")) \
#                           - (b.reserved_qty or Decimal("0"))
#
#     if not stock_is_generated and hasattr(Bin, "stock_value"):
#         b.stock_value = (b.actual_qty or Decimal("0")) * (b.valuation_rate or Decimal("0"))
#
#     s.flush([b])
#     logger.info(f"derive_bin: Finished. Bin now has actual_qty={b.actual_qty}, valuation_rate={b.valuation_rate}")
#     return b
#
#
# def derive_bins_for(s: Session, company_id: int, item_id: int, warehouse_ids: list[int]) -> None:
#     logger.info(f"derive_bins_for: Starting for item={item_id}, warehouses={warehouse_ids}")
#     for wh in warehouse_ids:
#         derive_bin(s, company_id, item_id, wh)

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import uuid4
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.inspection import inspect as sqla_inspect

from app.application_stock.stock_models import StockLedgerEntry, Bin

logger = logging.getLogger(__name__)


def _make_bin_code(s: Session, item_id: int, warehouse_id: int) -> str:
    for _ in range(4):
        code = uuid4().hex[:12]
        exists = s.execute(select(Bin.id).where(Bin.code == code).limit(1)).scalar_one_or_none()
        if not exists:
            return code
    return uuid4().hex


def _is_generated_column(model, attr_name: str) -> bool:
    mapper = sqla_inspect(model)
    col = mapper.columns.get(attr_name)
    return bool(getattr(col, "computed", None))


def ensure_bin(s: Session, *, company_id: int, item_id: int, warehouse_id: int) -> Bin:
    b: Optional[Bin] = s.execute(
        select(Bin)
        .where(Bin.company_id == company_id, Bin.item_id == item_id, Bin.warehouse_id == warehouse_id)
        .with_for_update()
    ).scalar_one_or_none()

    if not b:
        b = Bin(
            company_id=company_id,
            item_id=item_id,
            warehouse_id=warehouse_id,
            code=_make_bin_code(s, item_id, warehouse_id),
            actual_qty=Decimal("0"),
            reserved_qty=Decimal("0"),
            ordered_qty=Decimal("0"),
            valuation_rate=Decimal("0"),
        )
        s.add(b)
        s.flush([b])
        logger.info(f"Created new bin: {b.id}")
    return b


def derive_bin(s: Session, company_id: int, item_id: int, warehouse_id: int) -> Bin:
    last: Optional[StockLedgerEntry] = s.execute(
        select(StockLedgerEntry)
        .where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.warehouse_id == warehouse_id,
            StockLedgerEntry.is_cancelled == False,
        )
        .order_by(StockLedgerEntry.posting_date.desc(), StockLedgerEntry.posting_time.desc(), StockLedgerEntry.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    b = ensure_bin(s, company_id=company_id, item_id=item_id, warehouse_id=warehouse_id)

    b.actual_qty = last.qty_after_transaction if last else Decimal("0")
    b.valuation_rate = last.valuation_rate if last else Decimal("0")

    if not _is_generated_column(Bin, "projected_qty") and hasattr(Bin, "projected_qty"):
        b.projected_qty = (b.actual_qty or Decimal("0")) + (b.ordered_qty or Decimal("0")) - (b.reserved_qty or Decimal("0"))

    if not _is_generated_column(Bin, "stock_value") and hasattr(Bin, "stock_value"):
        b.stock_value = (b.actual_qty or Decimal("0")) * (b.valuation_rate or Decimal("0"))

    s.flush([b])
    return b


def derive_bins_for(s: Session, company_id: int, item_id: int, warehouse_ids: list[int]) -> None:
    for wh in warehouse_ids:
        derive_bin(s, company_id, item_id, wh)
