# app/application_buying/invoice_repo.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set
from sqlalchemy import select, func, exists, and_
from sqlalchemy.orm import Session, selectinload

# Project-specific imports (adjust paths as needed)
from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem, PurchaseInvoice, PurchaseInvoiceItem
from app.application_nventory.inventory_models import Item, ItemTypeEnum, UnitOfMeasure, UOMConversion
from app.application_parties.parties_models import Party, PartyRoleEnum
from app.application_stock.stock_models import Warehouse, DocStatusEnum

from config.database import db
from app.common.models.base import StatusEnum


class PurchaseInvoiceRepository:
    """Data Access Layer for Purchase Invoice documents."""

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    def get_by_id(self, pi_id: int, for_update: bool = False) -> Optional[PurchaseInvoice]:
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items))
            .where(PurchaseInvoice.id == pi_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
        stmt = select(exists().where(
            PurchaseInvoice.company_id == company_id,
            PurchaseInvoice.branch_id == branch_id,
            func.lower(PurchaseInvoice.code) == func.lower(code)
        ))
        if exclude_id:
            stmt = stmt.where(PurchaseInvoice.id != exclude_id)
        return self.s.execute(stmt).scalar()

    def get_receipt_billable_status(self, receipt_id: int) -> Dict:
        """
        Fetches a submitted Purchase Receipt and the quantities already billed against each item.
        This is critical to prevent over-billing.
        """
        # 1. Fetch the receipt and its items
        receipt = self.s.execute(
            select(PurchaseReceipt)
            .options(selectinload(PurchaseReceipt.items))
            .where(PurchaseReceipt.id == receipt_id, PurchaseReceipt.doc_status == DocStatusEnum.SUBMITTED)
        ).scalar_one_or_none()

        if not receipt:
            return {}

        # 2. Find all quantities already billed against this receipt's items
        receipt_item_ids = [item.id for item in receipt.items]
        billed_qty_stmt = (
            select(
                PurchaseInvoiceItem.receipt_item_id,
                func.sum(PurchaseInvoiceItem.quantity).label("total_billed")
            )
            .join(PurchaseInvoice)
            .where(
                PurchaseInvoiceItem.receipt_item_id.in_(receipt_item_ids),
                PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED
            )
            .group_by(PurchaseInvoiceItem.receipt_item_id)
        )

        billed_quantities = {row.receipt_item_id: row.total_billed for row in self.s.execute(billed_qty_stmt).all()}

        return {"receipt": receipt, "billed_quantities": billed_quantities}

    def save(self, pi: PurchaseInvoice) -> PurchaseInvoice:
        if pi not in self.s:
            self.s.add(pi)
        self.s.flush()
        return pi

    def sync_lines(self, pi: PurchaseInvoice, lines_data: List[Dict]) -> None:
        # This logic is identical to PurchaseReceipt.sync_lines
        existing_lines_map = {line.id: line for line in pi.items}
        lines_to_keep_ids: Set[int] = set()

        for line_data in lines_data:
            line_id = line_data.get("id")
            if line_id and line_id in existing_lines_map:
                line = existing_lines_map[line_id]
                for key, value in line_data.items():
                    if hasattr(line, key):
                        setattr(line, key, value)
                lines_to_keep_ids.add(line_id)
            else:
                new_line = PurchaseInvoiceItem(invoice_id=pi.id, **line_data)
                self.s.add(new_line)

        lines_to_delete_ids = set(existing_lines_map.keys()) - lines_to_keep_ids
        for line_id in lines_to_delete_ids:
            self.s.delete(existing_lines_map[line_id])