# # app/application_buying/invoice_repo.py
#
# from __future__ import annotations
# from typing import Optional, List, Dict, Tuple, Set
# from sqlalchemy import select, func, exists, and_
# from sqlalchemy.orm import Session, selectinload
#
# from app import Branch
# # Project-specific imports (adjust paths as needed)
# from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem, PurchaseInvoice, PurchaseInvoiceItem
# from app.application_nventory.inventory_models import Item, ItemTypeEnum, UnitOfMeasure, UOMConversion
# from app.application_parties.parties_models import Party, PartyRoleEnum
# from app.application_stock.stock_models import Warehouse, DocStatusEnum
#
# from config.database import db
# from app.common.models.base import StatusEnum
#
#
# class PurchaseInvoiceRepository:
#     """Data Access Layer for Purchase Invoice documents."""
#
#     def __init__(self, session: Optional[Session] = None):
#         self.s: Session = session or db.session
#
#     def get_by_id(self, pi_id: int, for_update: bool = False) -> Optional[PurchaseInvoice]:
#         stmt = (
#             select(PurchaseInvoice)
#             .options(selectinload(PurchaseInvoice.items))
#             .where(PurchaseInvoice.id == pi_id)
#         )
#         if for_update:
#             stmt = stmt.with_for_update()
#         return self.s.execute(stmt).scalar_one_or_none()
#
#     def code_exists(self, company_id: int, branch_id: int, code: str, exclude_id: Optional[int] = None) -> bool:
#         stmt = select(exists().where(
#             PurchaseInvoice.company_id == company_id,
#             PurchaseInvoice.branch_id == branch_id,
#             func.lower(PurchaseInvoice.code) == func.lower(code)
#         ))
#         if exclude_id:
#             stmt = stmt.where(PurchaseInvoice.id != exclude_id)
#         return self.s.execute(stmt).scalar()
#
#     def get_receipt_billable_status(self, receipt_id: int) -> Dict:
#         """
#         Fetches a submitted Purchase Receipt and the quantities already billed against each item.
#         This is critical to prevent over-billing.
#         """
#         # 1. Fetch the receipt and its items
#         receipt = self.s.execute(
#             select(PurchaseReceipt)
#             .options(selectinload(PurchaseReceipt.items))
#             .where(PurchaseReceipt.id == receipt_id, PurchaseReceipt.doc_status == DocStatusEnum.SUBMITTED)
#         ).scalar_one_or_none()
#
#         if not receipt:
#             return {}
#
#         # 2. Find all quantities already billed against this receipt's items
#         receipt_item_ids = [item.id for item in receipt.items]
#         billed_qty_stmt = (
#             select(
#                 PurchaseInvoiceItem.receipt_item_id,
#                 func.sum(PurchaseInvoiceItem.quantity).label("total_billed")
#             )
#             .join(PurchaseInvoice)
#             .where(
#                 PurchaseInvoiceItem.receipt_item_id.in_(receipt_item_ids),
#                 PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED
#             )
#             .group_by(PurchaseInvoiceItem.receipt_item_id)
#         )
#
#         billed_quantities = {row.receipt_item_id: row.total_billed for row in self.s.execute(billed_qty_stmt).all()}
#
#         return {"receipt": receipt, "billed_quantities": billed_quantities}
#
#     def save(self, pi: PurchaseInvoice) -> PurchaseInvoice:
#         if pi not in self.s:
#             self.s.add(pi)
#         self.s.flush()
#         return pi
#     def get_branch_company_id(self, branch_id: int) -> Optional[int]:
#         """
#         Return the company_id for a given branch, or None if not found.
#         Used by resolve_company_branch_and_scope() to canonicalize scope.
#         """
#         stmt = select(Branch.company_id).where(Branch.id == branch_id)
#         return self.s.execute(stmt).scalar_one_or_none()
#
#     def sync_lines(self, pi: PurchaseInvoice, lines_data: List[Dict]) -> None:
#         # This logic is identical to PurchaseReceipt.sync_lines
#         existing_lines_map = {line.id: line for line in pi.items}
#         lines_to_keep_ids: Set[int] = set()
#
#         for line_data in lines_data:
#             line_id = line_data.get("id")
#             if line_id and line_id in existing_lines_map:
#                 line = existing_lines_map[line_id]
#                 for key, value in line_data.items():
#                     if hasattr(line, key):
#                         setattr(line, key, value)
#                 lines_to_keep_ids.add(line_id)
#             else:
#                 new_line = PurchaseInvoiceItem(invoice_id=pi.id, **line_data)
#                 self.s.add(new_line)
#
#         lines_to_delete_ids = set(existing_lines_map.keys()) - lines_to_keep_ids
#         for line_id in lines_to_delete_ids:
#             self.s.delete(existing_lines_map[line_id])
# app/application_buying/invoice_repo.py

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
from sqlalchemy import select, func, exists, and_
from sqlalchemy.orm import Session, selectinload, aliased, joinedload

from app import Branch
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

    # --- Core Document Operations ---

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

    def save(self, pi: PurchaseInvoice) -> PurchaseInvoice:
        if pi not in self.s:
            self.s.add(pi)
        self.s.flush()
        return pi

    def sync_lines(self, pi: PurchaseInvoice, lines_data: List[Dict]) -> None:
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

    # --- Debit Note Specific Methods ---

    def get_original_for_debit_note(self, invoice_id: int, company_id: Optional[int] = None) -> Optional[
        PurchaseInvoice]:
        """
        Enhanced version with optional company validation.
        """
        stmt = (
            select(PurchaseInvoice)
            .options(
                selectinload(PurchaseInvoice.items)
                .selectinload(PurchaseInvoiceItem.item)
            )
            .where(
                PurchaseInvoice.id == invoice_id,
                PurchaseInvoice.doc_status == DocStatusEnum.SUBMITTED,
                PurchaseInvoice.is_return == False,
            )
        )

        # Optional company validation
        if company_id:
            stmt = stmt.where(PurchaseInvoice.company_id == company_id)

        stmt = stmt.with_for_update()
        return self.s.execute(stmt).scalar_one_or_none()

    def get_returned_quantities_for_invoice_items(self, original_item_ids: List[int]) -> Dict[int, Decimal]:
        """
        Calculates the total quantity already returned via debit notes for a set of original invoice items.
        Returns a dictionary: {original_item_id: total_returned_qty} (as a positive number).
        """
        if not original_item_ids:
            return {}

        # Alias for debit note items
        DebitNoteItem = aliased(PurchaseInvoiceItem)
        DebitNote = aliased(PurchaseInvoice)

        stmt = (
            select(
                DebitNoteItem.return_against_item_id,
                func.sum(DebitNoteItem.quantity).label("total_returned")
            )
            .join(DebitNote, DebitNote.id == DebitNoteItem.invoice_id)
            .where(
                DebitNoteItem.return_against_item_id.in_(original_item_ids),
                DebitNote.doc_status == DocStatusEnum.SUBMITTED,
                DebitNote.is_return == True,  # Only count debit notes/returns
            )
            .group_by(DebitNoteItem.return_against_item_id)
        )

        result = self.s.execute(stmt).all()
        # The sum is negative for debit notes; abs() makes it a positive value
        return {row.return_against_item_id: abs(row.total_returned) for row in result}

    # --- Receipt Billing Methods ---

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

    # --- Master Data Validation Methods ---

    def get_branch_company_id(self, branch_id: int) -> Optional[int]:
        """
        Return the company_id for a given branch, or None if not found.
        Used by resolve_company_branch_and_scope() to canonicalize scope.
        """
        stmt = select(Branch.company_id).where(Branch.id == branch_id)
        return self.s.execute(stmt).scalar_one_or_none()

    def get_valid_supplier_ids(self, company_id: int, supplier_ids: List[int]) -> Set[int]:
        """Returns the subset of supplier IDs that are valid and active."""
        if not supplier_ids:
            return set()
        stmt = select(Party.id).where(
            Party.id.in_(supplier_ids),
            Party.company_id == company_id,
            Party.role == PartyRoleEnum.SUPPLIER,
            Party.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_transactional_warehouse_ids(self, company_id: int, branch_id: int, warehouse_ids: List[int]) -> Set[int]:
        """
        Returns the subset of warehouse IDs that are valid, active, and not group warehouses (leaf nodes).
        """
        if not warehouse_ids:
            return set()

        # Alias for child warehouses
        W_child = aliased(Warehouse)

        # TRUE if a child exists for the outer Warehouse row
        child_exists = exists(
            select(1).where(W_child.parent_warehouse_id == Warehouse.id)
        )

        stmt = (
            select(Warehouse.id)
            .where(
                Warehouse.id.in_(warehouse_ids),
                Warehouse.company_id == company_id,
                Warehouse.branch_id == branch_id,
                Warehouse.status == StatusEnum.ACTIVE,
                ~child_exists,  # not a parent → i.e., leaf/transactional
            )
        )
        return set(self.s.execute(stmt).scalars().all())

    def get_item_details_batch(self, company_id: int, item_ids: List[int]) -> Dict[int, Dict]:
        """Fetches key details for a batch of items for validation."""
        if not item_ids:
            return {}

        stmt = select(Item.id, Item.status, Item.item_type, Item.base_uom_id).where(
            Item.id.in_(item_ids),
            Item.company_id == company_id  # ✅ CRITICAL: Filter by company_id
        )
        rows = self.s.execute(stmt).all()

        result = {
            r.id: {
                "is_active": r.status == StatusEnum.ACTIVE,
                "is_stock_item": r.item_type == ItemTypeEnum.STOCK_ITEM,
                "base_uom_id": r.base_uom_id
            }
            for r in rows
        }

        # Log for debugging
        logging.info(
            f"Item details batch query: company_id={company_id}, item_ids={item_ids}, found={list(result.keys())}")

        return result

    def get_existing_uom_ids(self, company_id: int, uom_ids: List[int]) -> Set[int]:
        """Returns the subset of UOM IDs that exist and are active."""
        if not uom_ids:
            return set()
        stmt = select(UnitOfMeasure.id).where(
            UnitOfMeasure.id.in_(uom_ids),
            UnitOfMeasure.company_id == company_id,
            UnitOfMeasure.status == StatusEnum.ACTIVE
        )
        return set(self.s.execute(stmt).scalars().all())
    def get_compatible_uom_pairs(self, company_id: int, pairs: List[Tuple[int, int]]) -> Set[Tuple[int, int]]:
        """Checks a batch of (item_id, uom_id) pairs for compatibility using the new UOMConversion model."""
        if not pairs:
            return set()

        item_ids = {p[0] for p in pairs}

        # Get base UOM for each item
        item_stmt = select(Item.id, Item.base_uom_id).where(Item.id.in_(item_ids))
        base_uom_map = dict(self.s.execute(item_stmt).all())

        # Get ALL active UOM conversions for these items
        conv_stmt = select(
            UOMConversion.item_id,
            UOMConversion.uom_id,
            UOMConversion.conversion_factor
        ).where(
            UOMConversion.item_id.in_(item_ids),
            UOMConversion.is_active == True
        )

        # Create a set of all valid (item_id, uom_id) pairs that have conversions
        valid_conversions = {(c.item_id, c.uom_id) for c in self.s.execute(conv_stmt).all()}

        # Also create a map for conversion factors if needed later
        conversion_factor_map = {(c.item_id, c.uom_id): c.conversion_factor for c in self.s.execute(conv_stmt).all()}

        compatible_pairs: Set[Tuple[int, int]] = set()

        for item_id, uom_id in pairs:
            base_uom_id = base_uom_map.get(item_id)
            if not base_uom_id:
                continue

            # A UOM is compatible if:
            # 1. It's the item's base UOM (always compatible), OR
            # 2. There's an active conversion defined for this (item_id, uom_id) combination
            if uom_id == base_uom_id or (item_id, uom_id) in valid_conversions:
                compatible_pairs.add((item_id, uom_id))

        return compatible_pairs

    # --- Additional Utility Methods ---

    def get_invoice_by_code(self, company_id: int, branch_id: int, code: str) -> Optional[PurchaseInvoice]:
        """Finds an invoice by its code within a specific company and branch."""
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items))
            .where(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.branch_id == branch_id,
                func.lower(PurchaseInvoice.code) == func.lower(code)
            )
        )
        return self.s.execute(stmt).scalar_one_or_none()

    def get_invoices_by_supplier(self, company_id: int, supplier_id: int,
                                 status: Optional[DocStatusEnum] = None) -> List[PurchaseInvoice]:
        """Gets all invoices for a specific supplier, optionally filtered by status."""
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items))
            .where(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.supplier_id == supplier_id
            )
        )
        if status:
            stmt = stmt.where(PurchaseInvoice.doc_status == status)

        stmt = stmt.order_by(PurchaseInvoice.posting_date.desc())
        return list(self.s.execute(stmt).scalars().all())

    def get_debit_notes_against_invoice(self, original_invoice_id: int) -> List[PurchaseInvoice]:
        """Gets all debit notes created against a specific original invoice."""
        stmt = (
            select(PurchaseInvoice)
            .options(selectinload(PurchaseInvoice.items))
            .where(
                PurchaseInvoice.return_against_id == original_invoice_id,
                PurchaseInvoice.is_return == True
            )
            .order_by(PurchaseInvoice.posting_date.desc())
        )
        return list(self.s.execute(stmt).scalars().all())

    def update_outstanding_amount(self, invoice_id: int, paid_amount: Decimal) -> None:
        """Updates the outstanding amount after a payment."""
        invoice = self.get_by_id(invoice_id, for_update=True)
        if invoice:
            invoice.paid_amount = paid_amount
            invoice.outstanding_amount = invoice.total_amount - paid_amount
            self.save(invoice)

    def cancel_invoice(self, invoice_id: int) -> Optional[PurchaseInvoice]:
        """Cancels an invoice by setting its status to CANCELLED."""
        invoice = self.get_by_id(invoice_id, for_update=True)
        if invoice and invoice.doc_status in [DocStatusEnum.DRAFT, DocStatusEnum.SUBMITTED]:
            invoice.doc_status = DocStatusEnum.CANCELLED
            self.save(invoice)
            return invoice
        return None

    def get_purchase_invoice_with_items(self, invoice_id: int) -> Optional[PurchaseInvoice]:
        """Get purchase invoice with items for debit note creation."""
        return self.s.query(PurchaseInvoice).options(
            joinedload(PurchaseInvoice.items)
        ).filter(PurchaseInvoice.id == invoice_id).first()