from __future__ import annotations

import logging
from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
from datetime import datetime

from sqlalchemy import and_, select, exists, or_, func
from werkzeug.exceptions import NotFound, Conflict
from sqlalchemy.orm import Session

from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.stock_models import DocumentType, StockLedgerEntry
from app.application_stock.engine.bin_derive import derive_bin
from app.application_stock.engine.handlers.purchase import build_intents_for_receipt, build_intents_for_return
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.business_validation.posting_date_validation import PostingDateValidator
from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import (
    ensure_scope_by_ids,
    resolve_company_branch_and_scope,
)

# Business Logic Imports
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum

# Validation helpers
import app.business_validation.item_validation as V
from app.common.timezone.service import get_company_timezone

# Import your models and schemas
from app.application_buying.models import PurchaseInvoice, PurchaseInvoiceItem
from app.application_buying.schemas import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceUpdate,
    PurchaseDebitNoteCreate,
    PurchaseDebitNoteItemCreate
)
from app.application_buying.repository.invoice_repo import PurchaseInvoiceRepository


class PurchaseInvoiceService:
    """Service layer for managing Purchase Invoices with financial + optional stock impact."""
    PREFIX = "PINV"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseInvoiceRepository(self.s)


    # ---- internal helpers ----------------------------------------------------
    def _get_validated_invoice(
            self, invoice_id: int, context: AffiliationContext, for_update: bool = False
    ) -> PurchaseInvoice:
        """Fetch, ensure scope to the persisted doc, and optionally lock."""
        invoice = self.repo.get_by_id(invoice_id, for_update=for_update)
        if not invoice:
            raise NotFound("Purchase Invoice not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=invoice.company_id,
            target_branch_id=invoice.branch_id,
        )
        return invoice

    def _generate_or_validate_code(
            self, company_id: int, branch_id: int, manual_code: Optional[str]
    ) -> str:
        """Generate a document code or validate a manually provided one."""
        if manual_code:
            code = manual_code.strip()
            if self.repo.code_exists(company_id, branch_id, code):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(
                prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=code
            )
            return code
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(self, company_id: int, branch_id: int, supplier_id: int, warehouse_id: Optional[int]) -> None:
        """Batch validate header-level master data."""
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)

        # Warehouse is optional for service-only invoices
        if warehouse_id:
            valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, branch_id, [warehouse_id])
            V.validate_warehouse_is_transactional(warehouse_id in valid_warehouses)

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict], is_return: bool) -> List[Dict]:
        """Validate item lines and enrich for processing."""
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.repo.get_item_details_batch(company_id, item_ids)

        # Create working copy with item details for validation
        working_lines = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        # Perform all validations using the working copy
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in working_lines])

        # For invoices, service items are allowed (unlike receipts)
        # Only validate UOM for stock items
        stock_lines = [ln for ln in working_lines if ln.get("is_stock_item", False)]
        if stock_lines:
            V.validate_uom_present_for_stock_items(stock_lines)

        uom_ids_to_check = [ln["uom_id"] for ln in working_lines if ln.get("uom_id")]
        if uom_ids_to_check:
            existing_uoms = self.repo.get_existing_uom_ids(company_id, uom_ids_to_check)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids_to_check])

        # UOM compatibility only for stock items
        uom_pairs = [(ln["item_id"], ln["uom_id"]) for ln in working_lines if
                     ln.get("uom_id") and ln.get("is_stock_item", False)]
        if uom_pairs:
            compatible_pairs = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
            for ln in working_lines:
                if ln.get("is_stock_item", False):
                    ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compatible_pairs
            V.validate_item_uom_compatibility([ln for ln in working_lines if ln.get("is_stock_item", False)])

        for ln in working_lines:
            # Quantity validation based on return status
            if is_return:
                # Debit notes have negative quantities
                if Decimal(str(ln.get("quantity", 0))) > 0:
                    raise V.BizValidationError("Debit note items must have negative quantities")
            else:
                # Normal invoices have positive quantities
                V.validate_positive_quantity(ln["quantity"])

            V.validate_non_negative_rate(ln.get("rate"))
            V.validate_positive_price(ln.get("rate"))

        # 🟢 FIX: Preserve the stock item fields for later filtering
        normalized_lines = []
        for ln in working_lines:
            clean_line = {
                "item_id": ln["item_id"],
                "uom_id": ln["uom_id"],
                "quantity": ln["quantity"],
                "rate": ln.get("rate"),
                "remarks": ln.get("remarks"),
                "receipt_item_id": ln.get("receipt_item_id"),
                # 🟢 CRITICAL: Preserve these fields for stock processing
                "is_stock_item": ln.get("is_stock_item", False),
                "base_uom_id": ln.get("base_uom_id")
            }
            # Preserve doc_row_id for submission if it exists
            if "doc_row_id" in ln:
                clean_line["doc_row_id"] = ln["doc_row_id"]

            normalized_lines.append(clean_line)

        return normalized_lines

    def _prepare_stock_lines(self, normalized_lines: List[Dict]) -> List[Dict]:
        """
        Prepare lines for stock engine with base_uom_id for UOM conversion.
        Only for stock items when update_stock is True.
        """
        stock_lines = []
        for ln in normalized_lines:
            # Get item details to check if it's a stock item
            item_details = self.repo.get_item_details_batch(ln.get('company_id', 0), [ln["item_id"]])
            is_stock_item = item_details.get(ln["item_id"], {}).get("is_stock_item", False)

            if is_stock_item:
                base_uom_id = item_details.get(ln["item_id"], {}).get("base_uom_id")
                stock_line = {
                    "item_id": ln["item_id"],
                    "uom_id": ln["uom_id"],
                    "quantity": ln["quantity"],  # Can be negative for returns
                    "rate": ln.get("rate"),
                    "doc_row_id": ln.get("doc_row_id"),
                    "base_uom_id": base_uom_id,
                    "is_stock_item": is_stock_item
                }
                stock_lines.append(stock_line)

        return stock_lines

    def _calculate_total_amount(self, company_id: int, lines: List[Dict]) -> Decimal:
        """
        Calculate total amount with proper UOM conversion for stock items.
        """
        from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing

        total = Decimal("0")

        for ln in lines:
            rate = ln.get("rate")
            if rate is None:
                continue

            quantity = Decimal(str(ln["quantity"]))
            rate_dec = Decimal(str(rate))

            # Get item details to check if it's a stock item
            item_details = self.repo.get_item_details_batch(company_id, [ln["item_id"]])
            item_detail = item_details.get(ln["item_id"], {})
            is_stock_item = item_detail.get("is_stock_item", False)
            base_uom_id = item_detail.get("base_uom_id")

            if not is_stock_item or not base_uom_id:
                # Service item or no base UOM - use transaction quantity directly
                line_total = quantity * rate_dec
                total += line_total
                continue

            # Stock item with UOM conversion
            uom_id = ln.get("uom_id")

            # Check if UOM conversion is needed
            if not uom_id or uom_id == base_uom_id:
                # No conversion needed
                line_total = quantity * rate_dec
            else:
                # Convert quantity to base UOM
                try:
                    base_qty_float, factor = to_base_qty(
                        qty=abs(quantity),  # Use absolute value for conversion
                        item_id=ln["item_id"],
                        uom_id=uom_id,
                        base_uom_id=base_uom_id,
                        strict=True
                    )
                    base_qty = Decimal(str(base_qty_float))

                    # Apply original sign (positive/negative) after conversion
                    if quantity < 0:
                        base_qty = -base_qty

                    line_total = base_qty * rate_dec
                except UOMFactorMissing:
                    # Fallback: use transaction quantity if conversion fails
                    line_total = quantity * rate_dec
                    logging.error(f"UOM conversion failed for item {ln['item_id']}, uom {uom_id}")

            total += line_total

        logging.info(f"Calculated total amount: ${total}")
        return total

    # ---- public API ----------------------------------------------------------

    def _validate_receipt_billing(self, invoice_lines: List[Dict], receipt_status: Dict) -> None:
        """Validate that invoice lines don't over-bill receipt items and rates match."""
        receipt = receipt_status["receipt"]
        billed_quantities = receipt_status["billed_quantities"]

        receipt_items_map = {item.id: item for item in receipt.items}

        for inv_line in invoice_lines:
            receipt_item_id = inv_line.get("receipt_item_id")
            if not receipt_item_id:
                continue

            receipt_item = receipt_items_map.get(receipt_item_id)
            if not receipt_item:
                raise V.BizValidationError(f"Receipt item {receipt_item_id} not found")

            # 🟢 CRITICAL FIX: Validate rate matches receipt rate
            if inv_line.get("rate") != receipt_item.unit_price:
                raise V.BizValidationError(
                    f"Rate must be same as Purchase Receipt: {receipt.code} "
                    f"({receipt_item.unit_price} / {inv_line.get('rate')})"
                )

            # Calculate available quantity to bill
            already_billed = billed_quantities.get(receipt_item_id, Decimal("0"))
            available_qty = receipt_item.accepted_qty - already_billed

            if inv_line["quantity"] > available_qty:
                raise V.BizValidationError(
                    f"Cannot bill quantity {inv_line['quantity']} for item {receipt_item.item_id}. "
                    f"Only {available_qty} available (received: {receipt_item.accepted_qty}, "
                    f"already billed: {already_billed})"
                )

    def create_purchase_invoice(self, *, payload: PurchaseInvoiceCreate,
                                context: AffiliationContext) -> PurchaseInvoice:
        """Create a NORMAL purchase invoice."""
        try:
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=payload.branch_id or getattr(context, "branch_id", None),
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )

            # Validate posting date
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=payload.posting_date,
                company_id=company_id,
            )
            logging.info("✅ Purchase invoice posting date validation passed")

            # 🟢 NEW: Validate receipt-based invoice logic
            if payload.receipt_id:
                # Invoice against receipt - validate receipt exists and get its details
                receipt_status = self.repo.get_receipt_billable_status(payload.receipt_id)
                if not receipt_status.get("receipt"):
                    raise V.BizValidationError("Receipt not found or not submitted")

                receipt = receipt_status["receipt"]
                billed_quantities = receipt_status["billed_quantities"]

                # Validate receipt belongs to same company/branch
                if receipt.company_id != company_id or receipt.branch_id != branch_id:
                    raise V.BizValidationError("Receipt does not belong to this company/branch")

                # Validate receipt has same supplier
                if receipt.supplier_id != payload.supplier_id:
                    raise V.BizValidationError("Invoice supplier must match receipt supplier")

                # 🟢 Validate that receipt_item_id belongs to the provided receipt_id
                receipt_item_ids = {item.id for item in receipt.items}
                for item in payload.items:
                    if item.receipt_item_id and item.receipt_item_id not in receipt_item_ids:
                        raise V.BizValidationError(
                            f"Receipt item ID {item.receipt_item_id} does not belong to receipt {payload.receipt_id}")

                # Use receipt's warehouse for validation
                warehouse_id = receipt.warehouse_id
            else:
                # Direct invoice - use provided warehouse
                warehouse_id = payload.warehouse_id

            # Validate header with correct warehouse_id
            self._validate_header(company_id, branch_id, payload.supplier_id, warehouse_id)

            # Validate and normalize lines
            lines_data = [ln.model_dump() for ln in payload.items]
            normalized_lines = self._validate_and_normalize_lines(company_id, lines_data, is_return=False)

            # 🟢 NEW: Additional validation for receipt-based invoices
            if payload.receipt_id:
                self._validate_receipt_billing(normalized_lines, receipt_status)

            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(company_id, normalized_lines)

            # Create PurchaseInvoiceItem
            invoice_items = []
            for ln in normalized_lines:
                item_data = {
                    "item_id": ln["item_id"],
                    "uom_id": ln["uom_id"],
                    "quantity": ln["quantity"],
                    "rate": ln.get("rate"),
                    "remarks": ln.get("remarks"),
                    "receipt_item_id": ln.get("receipt_item_id")
                }
                if "doc_row_id" in ln:
                    item_data["doc_row_id"] = ln["doc_row_id"]

                invoice_items.append(PurchaseInvoiceItem(**item_data))

            # Create invoice
            invoice = PurchaseInvoice(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=payload.supplier_id,
                warehouse_id=warehouse_id,  # 🟢 Use correct warehouse_id
                payable_account_id=payload.payable_account_id,
                code=code,
                dated=payload.dated or payload.posting_date,  # ← FIX: Use dated if provided, else use posting_date
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                update_stock=payload.update_stock,
                is_return=False,
                is_debit_note=False,
                total_amount=total_amount,
                paid_amount=Decimal("0"),
                outstanding_amount=total_amount,
                due_date=payload.due_date,
                remarks=payload.remarks,
                items=invoice_items,
                receipt_id=payload.receipt_id,  # 🟢 CRITICAL: Save receipt_id
            )

            self.repo.save(invoice)
            self.s.commit()
            logging.info(f"Created purchase invoice {invoice.code} (ID: {invoice.id})")
            return invoice

        except Exception as e:
            self.s.rollback()
            logging.error(f"Failed to create purchase invoice: {str(e)}")
            raise

    def create_purchase_debit_note(self, *, original_invoice_id: int, payload: PurchaseDebitNoteCreate,
                                   context: AffiliationContext) -> PurchaseInvoice:
        """Create a Purchase Debit Note against an original submitted invoice (ERPNext Style)."""
        try:
            logging.info(f"🔄 CREATE DEBIT NOTE STARTED: invoice_id={original_invoice_id}")

            # Get original invoice with complete details
            original_invoice = self.repo.get_purchase_invoice_with_items(original_invoice_id)
            if not original_invoice:
                raise V.BizValidationError("Original purchase invoice not found.")

            # Validate original invoice status
            if original_invoice.doc_status != DocStatusEnum.SUBMITTED:
                raise V.BizValidationError("Debit note can only be created against a SUBMITTED purchase invoice.")

            # Company validation
            if original_invoice.company_id != context.company_id:
                raise V.BizValidationError("Original invoice does not belong to your company.")

            # 🟢 POSTING DATE VALIDATION
            PostingDateValidator.validate_return_against_original(
                s=self.s,
                current_posting_date=payload.posting_date,
                original_document_date=original_invoice.posting_date,
                company_id=original_invoice.company_id,
            )
            logging.info("✅ Debit note posting date validation passed")

            # 🟢 BRANCH RESOLUTION (Same as purchase invoice)
            if payload.branch_id is not None:
                branch_id = payload.branch_id
                company_id = self.repo.get_branch_company_id(branch_id)
                if not company_id:
                    raise V.BizValidationError("Invalid branch_id provided.")
                if company_id != original_invoice.company_id:
                    raise V.BizValidationError("Branch does not belong to the same company as the original invoice.")
            else:
                company_id = original_invoice.company_id
                branch_id = original_invoice.branch_id

            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=branch_id,
            )

            # 🟢 VALIDATE DEBIT NOTE ITEMS WITH RATE MATCHING
            validated_debit_items = self._validate_debit_note_items(original_invoice, payload.items)

            # 🟢 WAREHOUSE VALIDATION
            warehouse_id = original_invoice.warehouse_id
            if payload.update_stock and not warehouse_id:
                raise V.BizValidationError("Cannot update stock: original invoice has no warehouse.")

            # 🟢 VALIDATE HEADER (similar to purchase invoice)
            self._validate_header(company_id, branch_id, original_invoice.supplier_id, warehouse_id)

            # Generate code and calculate total
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(company_id, validated_debit_items)

            # 🟢 CREATE DEBIT NOTE ITEMS WITH NEGATIVE QUANTITIES
            debit_note_items = []
            for ln in validated_debit_items:
                item_data = {
                    "item_id": ln["item_id"],
                    "uom_id": ln["uom_id"],
                    "quantity": ln["quantity"],  # Negative for debit notes
                    "rate": ln["rate"],
                    "remarks": ln.get("remarks"),
                    "return_against_item_id": ln.get("return_against_item_id"),
                    "receipt_item_id": ln.get("receipt_item_id")
                }
                debit_note_items.append(PurchaseInvoiceItem(**item_data))

            # 🟢 CREATE DEBIT NOTE DOCUMENT
            debit_note = PurchaseInvoice(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=original_invoice.supplier_id,
                warehouse_id=warehouse_id,
                payable_account_id=original_invoice.payable_account_id,
                code=code,
                dated=payload.dated,
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                update_stock=payload.update_stock,
                is_return=True,
                is_debit_note=True,
                return_against_id=original_invoice.id,
                total_amount=total_amount,  # Negative amount for debit note
                paid_amount=Decimal("0"),
                outstanding_amount=total_amount,
                due_date=payload.due_date,
                remarks=payload.remarks,
                items=debit_note_items,
            )

            self.repo.save(debit_note)
            self.s.commit()

            logging.info(f"✅ DEBIT NOTE CREATED: ID={debit_note.id}, Code={debit_note.code}")
            return debit_note

        except Exception as e:
            logging.error(f"❌ FAILED TO CREATE DEBIT NOTE: {str(e)}")
            self.s.rollback()
            raise

    def _validate_debit_note_items(self, original_invoice: PurchaseInvoice,
                                   debit_items: List[PurchaseDebitNoteItemCreate]) -> List[Dict]:
        """Validate debit note items against original invoice with rate matching."""
        logging.info(f"🔍 VALIDATING DEBIT NOTE ITEMS against invoice {original_invoice.id}")

        # Create mapping of original items
        original_items_map = {item.id: item for item in original_invoice.items}

        # Get previously returned quantities
        original_item_ids = [item.original_item_id for item in debit_items]
        previously_returned_qtys = self.repo.get_returned_quantities_for_invoice_items(original_item_ids)

        validated_lines = []

        for line in debit_items:
            original_item = original_items_map.get(line.original_item_id)

            if not original_item:
                raise V.BizValidationError(f"Original invoice item {line.original_item_id} not found.")

            # 🟢 VALIDATE QUANTITY AVAILABILITY
            previously_returned = previously_returned_qtys.get(line.original_item_id, Decimal("0"))
            original_quantity = Decimal(str(original_item.quantity))
            balance_qty = original_quantity - previously_returned

            if line.return_qty > balance_qty:
                raise V.BizValidationError(
                    f"Cannot return quantity {line.return_qty} for item {original_item.item_id}. "
                    f"Only {balance_qty} available (original: {original_quantity}, "
                    f"already returned: {previously_returned})"
                )

            # 🟢 CRITICAL: USE ORIGINAL RATE (ERPNext Style)
            # Debit note must use the same rate as original invoice
            original_rate = original_item.rate

            # Create debit note line with NEGATIVE quantity
            validated_lines.append({
                "item_id": original_item.item_id,
                "uom_id": original_item.uom_id,
                "quantity": -abs(line.return_qty),  # Negative for returns
                "rate": original_rate,  # Same rate as original invoice
                "remarks": line.remarks,
                "return_against_item_id": line.original_item_id,
                "receipt_item_id": original_item.receipt_item_id,  # Preserve receipt link if exists
            })

            logging.info(f"✅ Debit note item validated: Item {original_item.item_id}, "
                         f"Qty: {-abs(line.return_qty)}, Rate: {original_rate}")

        return validated_lines

    def get_stock_intents_data(self, invoice: PurchaseInvoice) -> List[Dict]:
        """Prepare data for stock engine - only if update_stock is True."""
        stock_lines = []

        if not invoice.update_stock:
            return stock_lines

        for item in invoice.items:
            # Get item details to check if it's a stock item
            item_details = self.repo.get_item_details_batch(invoice.company_id, [item.item_id])
            is_stock_item = item_details.get(item.item_id, {}).get("is_stock_item", False)

            if is_stock_item:
                base_uom_id = item_details.get(item.item_id, {}).get("base_uom_id")
                stock_line = {
                    "item_id": item.item_id,
                    "uom_id": item.uom_id,
                    "quantity": item.quantity,  # Can be negative for debit notes
                    "rate": item.rate,
                    "doc_row_id": item.id,
                    "base_uom_id": base_uom_id,
                    "is_stock_item": is_stock_item
                }
                stock_lines.append(stock_line)

        return stock_lines

    def guard_purchase_invoice_submittable(self, invoice: PurchaseInvoice) -> None:
        """
        Purchase invoice-specific submission guard.
        """
        # Use existing global guard for basic DRAFT check
        V.guard_submittable_state(invoice.doc_status)

        if invoice.is_return:
            # Debit note specific validations
            if invoice.doc_status == DocStatusEnum.RETURNED:
                raise V.BizValidationError("Debit note has already been processed.")
            if not invoice.return_against_id:
                raise V.BizValidationError("Debit note must reference an original invoice.")
        else:
            # Normal invoice specific validations
            if invoice.doc_status == DocStatusEnum.SUBMITTED:
                raise V.BizValidationError("Purchase invoice has already been submitted.")

    def submit_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        """
        Submit a Purchase Invoice or Debit Note.

        ERP rules:
        - If against a Purchase Receipt -> financial-only; GL clears GRNI (2210) and credits A/P.
        - Direct invoice -> GL posts per PURCHASE_INVOICE_DIRECT; stock only if update_stock=True.
        """
        try:
            # ---- 1) READ PHASE (no locks) ---------------------------------------
            logging.info("PINV submit: start invoice_id=%s", invoice_id)

            invoice = self._get_validated_invoice(invoice_id, context, for_update=False)

            # Validate posting date at submission
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=invoice.posting_date,
                company_id=invoice.company_id,
            )

            self.guard_purchase_invoice_submittable(invoice)
            V.validate_list_not_empty(invoice.items, "items for submission")

            # Warehouse validation only matters when update_stock=True (direct PI with stock)
            if invoice.update_stock and not invoice.warehouse_id:
                raise V.BizValidationError("Warehouse is required for stock invoices.")

            if invoice.warehouse_id:
                self._validate_header(invoice.company_id, invoice.branch_id, invoice.supplier_id, invoice.warehouse_id)

            # Timezone
            from app.common.timezone.service import get_company_timezone
            company_tz = get_company_timezone(self.s, invoice.company_id)
            logging.info("PINV submit: Using company timezone: %s", company_tz)

            # Doc type
            is_debit_note = invoice.is_return
            doc_type_code = "PURCHASE_RETURN" if is_debit_note else "PURCHASE_INVOICE"

            logging.info(
                "PINV submit: Processing %s | invoice_id=%s code=%s update_stock=%s",
                "DEBIT NOTE" if is_debit_note else "INVOICE",
                invoice.id, invoice.code, invoice.update_stock
            )
            logging.info("PINV submit: Raw items from invoice: %s", [
                {"item_id": i.item_id, "quantity": i.quantity, "uom_id": i.uom_id}
                for i in invoice.items
            ])

            # ---- stock_lines only if this is a direct PI with stock --------------
            stock_lines = []
            if invoice.update_stock:
                # Guard: you cannot both reference a receipt and try to post stock on the invoice
                if invoice.receipt_id:
                    raise V.BizValidationError(
                        "Invoice against a Purchase Receipt must not update stock. Use financial-only PI.")

                item_ids = [item.item_id for item in invoice.items]
                item_details = self.repo.get_item_details_batch(invoice.company_id, item_ids)
                lines_snap = [{
                    "item_id": i.item_id,
                    "uom_id": i.uom_id,
                    "quantity": i.quantity,
                    "rate": i.rate,
                    "doc_row_id": i.id,
                    "base_uom_id": item_details.get(i.item_id, {}).get("base_uom_id"),
                    "is_stock_item": item_details.get(i.item_id, {}).get("is_stock_item", False)
                } for i in invoice.items]

                norm = self._validate_and_normalize_lines(invoice.company_id, lines_snap, is_debit_note)
                stock_lines = [ln for ln in norm if
                               ln.get("is_stock_item", False) and Decimal(str(ln.get("quantity", 0))) != 0]
                logging.info("PINV submit: Final stock_lines: %s", stock_lines)

                if stock_lines:  # Only validate if there are actual stock lines
                    V.validate_list_not_empty(stock_lines, "stock items for submission")

            doc_type_id = self._get_doc_type_id_or_400(doc_type_code)

            # Posting datetime
            posting_dt = resolve_posting_dt(
                invoice.posting_date.date() if hasattr(invoice.posting_date, "date") else invoice.posting_date,
                created_at=invoice.created_at,
                tz=company_tz,
                treat_midnight_as_date=True,
            )
            logging.info("PINV submit: posting_dt=%s (timezone: %s)", posting_dt, posting_dt.tzinfo)

            # ---- 2) ATOMIC WRITE PHASE (SAVEPOINT) ------------------------------
            with self.s.begin_nested():
                invoice_locked = self._get_validated_invoice(invoice_id, context, for_update=True)
                self.guard_purchase_invoice_submittable(invoice_locked)

                # 2a) Stock processing only for direct PI with stock
                if invoice_locked.update_stock and stock_lines:
                    stock_engine_lines = [{
                        "uom_id": ln["uom_id"],
                        "item_id": ln["item_id"],
                        "accepted_qty": ln["quantity"],  # map qty
                        "unit_price": ln["rate"],  # map rate
                        "doc_row_id": ln["doc_row_id"],
                        "base_uom_id": ln.get("base_uom_id"),
                    } for ln in stock_lines]

                    if is_debit_note:
                        logging.info("PINV submit: Building RETURN intents for debit note (direct PI with stock)")
                        intents = build_intents_for_return(
                            company_id=invoice_locked.company_id,
                            branch_id=invoice_locked.branch_id,
                            warehouse_id=invoice_locked.warehouse_id,
                            posting_dt=posting_dt,
                            doc_type_id=doc_type_id,
                            doc_id=invoice_locked.id,
                            lines=stock_engine_lines,
                            session=self.s,
                        )
                    else:
                        logging.info("PINV submit: Building RECEIPT intents for direct PI with stock")
                        intents = build_intents_for_receipt(
                            company_id=invoice_locked.company_id,
                            branch_id=invoice_locked.branch_id,
                            warehouse_id=invoice_locked.warehouse_id,
                            posting_dt=posting_dt,
                            doc_type_id=doc_type_id,
                            doc_id=invoice_locked.id,
                            lines=stock_engine_lines,
                            session=self.s,
                        )

                    if intents:
                        pairs = {(i.item_id, i.warehouse_id) for i in intents}
                        logging.info("PINV submit: Stock intents generated | pairs=%s", list(pairs))

                        # Backdating detection
                        def _has_future_sle(item_id: int, wh_id: int) -> bool:
                            q = self.s.execute(
                                select(func.count()).select_from(StockLedgerEntry).where(
                                    StockLedgerEntry.company_id == invoice_locked.company_id,
                                    StockLedgerEntry.item_id == item_id,
                                    StockLedgerEntry.warehouse_id == wh_id,
                                    (
                                            (StockLedgerEntry.posting_date > posting_dt.date()) |
                                            and_(
                                                StockLedgerEntry.posting_date == posting_dt.date(),
                                                StockLedgerEntry.posting_time > posting_dt,
                                            )
                                    ),
                                    StockLedgerEntry.is_cancelled == False,
                                )
                            ).scalar()
                            return (q or 0) > 0

                        is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
                        logging.info("PINV submit: backdated=%s | pairs=%s", is_backdated, list(pairs))

                        sle_written = 0
                        with lock_pairs(self.s, pairs):
                            for idx, intent in enumerate(intents):
                                logging.info("PINV submit: Final intent for SLE before append: %s", {
                                    "item_id": intent.item_id,
                                    "warehouse_id": intent.warehouse_id,
                                    "actual_qty": intent.actual_qty,
                                    "incoming_rate": intent.incoming_rate,
                                    "outgoing_rate": intent.outgoing_rate,
                                    "doc_id": intent.doc_id,
                                    "is_return": is_debit_note,
                                    "meta": getattr(intent, "meta", {}),
                                })

                                sle = append_sle(
                                    self.s,
                                    intent,
                                    created_at_hint=invoice_locked.created_at,
                                    tz_hint=company_tz,
                                    batch_index=idx,
                                )
                                sle_written += 1
                                logging.info(
                                    "PINV submit: SLE appended | invoice_id=%s sle_id=%s item_id=%s",
                                    invoice_locked.id, sle.id, intent.item_id
                                )

                        if sle_written != len(intents):
                            raise RuntimeError(f"SLE append mismatch (expected {len(intents)}, wrote {sle_written}).")

                        # Backdated replay
                        if is_backdated:
                            for item_id, wh_id in pairs:
                                logging.info("PINV submit: Starting replay for item=%s, wh=%s", item_id, wh_id)
                                repost_from(
                                    s=self.s,
                                    company_id=invoice_locked.company_id,
                                    item_id=item_id,
                                    warehouse_id=wh_id,
                                    start_dt=posting_dt,
                                    exclude_doc_types=set()
                                )
                            logging.info("PINV submit: replay done for pairs=%s", list(pairs))

                        # Derive BINs
                        bins_updated = 0
                        for item_id, wh_id in pairs:
                            logging.info("PINV submit: Deriving bin for item=%s, wh=%s", item_id, wh_id)
                            bin_obj = derive_bin(self.s, invoice_locked.company_id, item_id, wh_id)
                            bins_updated += 1

                        logging.info("PINV submit: bins derived | invoice_id=%s bins_updated=%s", invoice_locked.id,
                                     bins_updated)
                    else:
                        logging.warning("PINV submit: No stock intents generated despite having stock lines")

                # 2b) GL posting (ALWAYS for invoices) -----------------------------
                # Decide template
                has_receipt_items = any(it.receipt_item_id for it in invoice_locked.items)
                if is_debit_note:
                    template_code = "PURCHASE_RETURN_INVOICED"
                    amount_source_key = "RETURN_DOCUMENT_TOTAL"
                    logging.info("PINV submit: Using PURCHASE_RETURN_INVOICED template (debit note)")
                else:
                    if invoice_locked.receipt_id or has_receipt_items:
                        template_code = "PURCHASE_INVOICE_AGAINST_RECEIPT"
                        amount_source_key = "DOCUMENT_TOTAL"
                        logging.info("PINV submit: Using PURCHASE_INVOICE_AGAINST_RECEIPT template (against receipt)")
                    else:
                        template_code = "PURCHASE_INVOICE_DIRECT"
                        amount_source_key = "DOCUMENT_TOTAL"
                        logging.info("PINV submit: Using PURCHASE_INVOICE_DIRECT template (direct invoice)")

                # Amounts
                total_amount = abs(Decimal(str(invoice_locked.total_amount or 0)))

                # Matched value for clearing GRNI when against receipt
                matched_grni_value = sum(
                    abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                    for it in invoice_locked.items if it.receipt_item_id
                )

                # Resolve payable account (default 2111 if none)
                payable_account_id = invoice_locked.payable_account_id
                if not payable_account_id:
                    payable_account_id = self._get_default_payable_account(invoice_locked.company_id)
                    logging.info("PINV submit: Using default payable account: %s", payable_account_id)

                dynamic_account_context = {
                    "accounts_payable_account_id": payable_account_id
                }

                # Build payload
                payload = {
                    "invoice_lines": [
                        {"quantity": it.quantity, "rate": it.rate, "item_id": it.item_id}
                        for it in invoice_locked.items
                    ],
                    amount_source_key: float(total_amount),  # DOCUMENT_TOTAL / RETURN_DOCUMENT_TOTAL
                    "update_stock": bool(invoice_locked.update_stock),
                }

                # 🟢 CRITICAL FIX: Add RETURN_STOCK_VALUE for debit notes
                if is_debit_note:
                    # Calculate the stock value being returned
                    return_stock_value = sum(
                        abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                        for it in invoice_locked.items
                    )
                    payload["RETURN_STOCK_VALUE"] = float(return_stock_value)
                    logging.info("PINV submit: Added RETURN_STOCK_VALUE=%.2f for debit note", float(return_stock_value))

                # Add matched GRNI only when using the against-receipt template
                if template_code == "PURCHASE_INVOICE_AGAINST_RECEIPT":
                    payload["INVOICE_MATCHED_GRNI_VALUE"] = float(matched_grni_value)
                    payload["receipt_id"] = invoice_locked.receipt_id
                    payload["has_receipt_items"] = has_receipt_items

                ctx = PostingContext(
                    company_id=invoice_locked.company_id,
                    branch_id=invoice_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=invoice_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"{'Purchase Debit Note' if is_debit_note else 'Purchase Invoice'} {invoice_locked.code}",
                    template_code=template_code,
                    payload=payload,
                    runtime_accounts={},
                    party_id=invoice_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                    dynamic_account_context=dynamic_account_context,
                )

                logging.info(
                    "PINV submit: GL posting with template=%s, total_amount=%.2f%s",
                    template_code, float(total_amount),
                    f", matched_grni={float(matched_grni_value):.2f}" if template_code == "PURCHASE_INVOICE_AGAINST_RECEIPT" else ""
                )
                PostingService(self.s).post(ctx)
                logging.info("PINV submit: GL posted | invoice_id=%s template=%s", invoice_locked.id, template_code)

                # 2c) Mark final status
                final_status = DocStatusEnum.RETURNED if is_debit_note else DocStatusEnum.SUBMITTED
                invoice_locked.doc_status = final_status
                self.repo.save(invoice_locked)
                logging.info("PINV submit: status -> %s | invoice_id=%s code=%s",
                             final_status.value, invoice_locked.id, invoice_locked.code)

            # ---- 3) COMMIT OUTER TX ---------------------------------------------
            logging.info("PINV submit: committing outer transaction for invoice_id=%s", invoice.id)
            self.s.commit()

            # ---- 4) Post-commit SLE sanity check --------------------------------
            try:
                cnt = self.s.execute(
                    select(func.count()).select_from(StockLedgerEntry).where(
                        StockLedgerEntry.company_id == invoice.company_id,
                        StockLedgerEntry.doc_type_id == doc_type_id,
                        StockLedgerEntry.doc_id == invoice.id,
                        StockLedgerEntry.is_cancelled == False,
                    )
                ).scalar()
                logging.info("DEBUG post-commit: SLE count for PINV id=%s -> %s", invoice.id, cnt)
            except Exception:
                logging.exception("DEBUG post-commit: failed to count SLE for PINV")

            logging.info("PINV submit: success | invoice_id=%s code=%s status=%s",
                         invoice.id, invoice.code, final_status.value)
            return invoice

        except Exception:
            logging.exception("PINV submit: FAILED (rolled back) | invoice_id=%s", invoice_id)
            self.s.rollback()
            raise


    def _get_default_payable_account(self, company_id: int) -> int:
        """
        Get the default Accounts Payable account for a company.
        ONLY uses account code '2111' (Creditors).

        Raises: BizValidationError if account 2111 not found.
        """
        from app.application_accounting.chart_of_accounts.models import Account

        # ONLY look for account code '2111'
        stmt = select(Account.id).where(
            Account.company_id == company_id,
            Account.code == '2111',
            Account.is_active == True
        )
        account_id = self.s.execute(stmt).scalar_one_or_none()

        if account_id:
            logging.info(f"Found default payable account 2111: {account_id}")
            return account_id

        # If 2111 not found, raise clear error
        raise V.BizValidationError(
            "Default Accounts Payable account (2111 - Creditors) not found. "
            "Please set up account 2111 in your chart of accounts "
            "or specify a payable account when creating the purchase invoice."
        )


    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt