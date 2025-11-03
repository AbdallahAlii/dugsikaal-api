# app/application_stock/services/availability_service.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence, Iterable

from sqlalchemy.orm import Session

from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.application_stock.repo.availability_repo import StockAvailabilityRepository

def _dec6(v: Decimal) -> str:
    return f"{v:.6f}"

class StockAvailabilityService:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = StockAvailabilityRepository(self.s)

    def compute_single(
        self,
        *,
        context: AffiliationContext,
        item_id: int,
        warehouse_ids: Sequence[int] | None,
        uom_id: Optional[int],
        at: Optional[datetime],
        detail: bool,
    ) -> dict:
        """
        ERPNext-style:
        - Availability is in Stock UOM (base) and does not depend on `uom_id`.
        - If detail=True and uom_id is given, include `available_txn` purely for display.
        """
        company_id = getattr(context, "company_id", None)
        if not company_id:
            raise PermissionError("Missing company scope.")

        wh_ids = list(warehouse_ids or [])
        item = self.repo.get_item_core(company_id, item_id)

        # Non-existent, inactive, non-stock, or no warehouses -> zero
        if not item or not item["is_active"] or not item["is_stock_item"] or not wh_ids:
            if not detail:
                return {"available": "0.000000"}
            out = {
                "item_id": item_id,
                "warehouse_ids": wh_ids,
                "base_uom_id": item["base_uom_id"] if item else None,
                "actual_qty": "0.000000",
                "reserved_qty": "0.000000",
                "ordered_qty": "0.000000",
                "projected_qty": "0.000000",
                "available": "0.000000",
            }
            # optional display-only conversion
            if detail and uom_id:
                out["available_txn"] = "0.000000"
                out["uom_id"] = uom_id
            return out

        # Latest (Bins) or As-of (SLE)
        if at:
            actual_asof = self.repo.sum_sle_as_of(company_id, item_id, wh_ids, at)
            actual = actual_asof
            reserved = Decimal("0")
            ordered = Decimal("0")
            projected = actual_asof  # as-of: reservations/orders unknown
        else:
            b = self.repo.sum_bins(company_id, item_id, wh_ids)
            actual = b["actual"]
            reserved = b["reserved"]
            ordered = b["ordered"]
            projected = (b["actual"] - b["reserved"] + b["ordered"])

        # Canonical availability in Stock UOM (like ERPNext)
        available_base = projected

        if not detail:
            return {"available": _dec6(available_base)}

        out = {
            "item_id": item_id,
            "warehouse_ids": wh_ids,
            "base_uom_id": item["base_uom_id"],
            "actual_qty": _dec6(actual),
            "reserved_qty": _dec6(reserved),
            "ordered_qty": _dec6(ordered),
            "projected_qty": _dec6(projected),
            "available": _dec6(available_base),  # base (Stock UOM)
        }

        # Optional: convenience for UI display if a txn UOM is selected
        if uom_id:
            factor = self.repo.get_factor(item_id, uom_id, item["base_uom_id"])  # 1 txn = factor base
            out["uom_id"] = uom_id
            out["available_txn"] = _dec6(available_base / factor if factor else Decimal("0"))
        return out

    def compute_batch(
        self,
        *,
        context: AffiliationContext,
        lines: Iterable[dict],
        at: Optional[datetime],
        detail: bool,
    ) -> list[dict]:
        out: list[dict] = []
        for ln in lines:
            res = self.compute_single(
                context=context,
                item_id=int(ln["item_id"]),
                warehouse_ids=ln.get("warehouse_ids") or [],
                uom_id=ln.get("uom_id"),          # ignored for base availability; only used to add available_txn in detail
                at=at,
                detail=detail,
            )
            row_id = ln.get("row_id")
            out.append({"row_id": row_id, **res} if row_id is not None else res)
        return out
