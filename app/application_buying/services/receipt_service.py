from __future__ import annotations

import logging

from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum

from sqlalchemy import and_, select, exists, or_
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
    ensure_scope_by_ids,                 # used for persisted docs
    resolve_company_branch_and_scope,    # << Way B (canonicalize + scope)
)

# Business Logic Imports
from app.common.generate_code.service import (
    generate_next_code,
    ensure_manual_code_is_next_and_bump,
)
from app.application_stock.stock_models import DocStatusEnum, StockLedgerEntry, DocumentType
from app.application_buying.repository.receipt_repo import PurchaseReceiptRepository
from app.application_buying.schemas import PurchaseReceiptCreate, PurchaseReceiptUpdate, PurchaseReturnCreate, \
    PurchaseReturnItemCreate
from app.application_buying.models import PurchaseReceipt, PurchaseReceiptItem

# Validation helpers
import app.business_validation.item_validation as V
from datetime import datetime, time, timezone, date, timedelta
import logging
logging.basicConfig(level=logging.DEBUG)
from app.common.timezone.service import get_company_timezone



class PurchaseReceiptService:
    """Service layer for managing Purchase Receipts with a strict workflow."""
    PREFIX = "PR"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseReceiptRepository(self.s)

    # ---- internal helpers ----------------------------------------------------
    def _get_validated_receipt(
        self, receipt_id: int, context: AffiliationContext, for_update: bool = False
    ) -> PurchaseReceipt:
        """Fetch, ensure scope to the persisted doc, and optionally lock."""
        pr = self.repo.get_by_id(receipt_id, for_update=for_update)
        if not pr:
            raise NotFound("Purchase Receipt not found.")
        ensure_scope_by_ids(
            context=context,
            target_company_id=pr.company_id,
            target_branch_id=pr.branch_id,
        )
        return pr

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

    def _validate_header(self, company_id: int, branch_id: int, supplier_id: int, warehouse_id: int) -> None:
        """Batch validate header-level master data."""
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)

        valid_warehouses = self.repo.get_transactional_warehouse_ids(company_id, branch_id, [warehouse_id])
        V.validate_warehouse_is_transactional(warehouse_id in valid_warehouses)

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict], is_return: bool) -> List[Dict]:
        """Validate item lines and enrich for stock processing."""
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        item_details = self.repo.get_item_details_batch(company_id, item_ids)

        # Create working copy with item details for validation
        working_lines = [{**ln, **item_details.get(ln["item_id"], {})} for ln in lines]

        # Perform all validations using the working copy
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in working_lines])
        V.validate_no_service_items(working_lines)
        V.validate_uom_present_for_stock_items(working_lines)

        uom_ids_to_check = [ln["uom_id"] for ln in working_lines if ln.get("uom_id")]
        if uom_ids_to_check:
            existing_uoms = self.repo.get_existing_uom_ids(company_id, uom_ids_to_check)
            V.validate_uoms_exist([(uid, uid in existing_uoms) for uid in uom_ids_to_check])

        uom_pairs = [(ln["item_id"], ln["uom_id"]) for ln in working_lines if ln.get("uom_id")]
        compatible_pairs = self.repo.get_compatible_uom_pairs(company_id, uom_pairs)
        for ln in working_lines:
            ln["uom_ok"] = (ln["item_id"], ln.get("uom_id")) in compatible_pairs
        V.validate_item_uom_compatibility(working_lines)

        for ln in working_lines:
            # 🚨 FIX 2b: Only validate for positive quantity if it's NOT a return
            if not is_return:
                V.validate_positive_quantity(ln["received_qty"])

            V.validate_accepted_quantity_logic(ln["received_qty"], ln["accepted_qty"])
            V.validate_positive_price(ln.get("unit_price"))

        # ✅ CORRECTED: Only include fields that exist in PurchaseReceiptItem model
        normalized_lines = []
        for ln in working_lines:
            clean_line = {
                "item_id": ln["item_id"],
                "uom_id": ln["uom_id"],
                "received_qty": ln["received_qty"],
                "accepted_qty": ln["accepted_qty"],
                "unit_price": ln.get("unit_price"),
                "remarks": ln.get("remarks")
            }
            # ✅ Preserve doc_row_id for submission if it exists
            if "doc_row_id" in ln:
                clean_line["doc_row_id"] = ln["doc_row_id"]

            normalized_lines.append(clean_line)

        return normalized_lines

    def _prepare_stock_lines(self, normalized_lines: List[Dict]) -> List[Dict]:
        """
        Prepare lines for stock engine with base_uom_id for UOM conversion.
        This is separate from the model creation.
        """
        stock_lines = []
        for ln in normalized_lines:
            # Get base_uom_id from item details for UOM conversion
            item_details = self.repo.get_item_details_batch(ln.get('company_id', 0), [ln["item_id"]])
            base_uom_id = item_details.get(ln["item_id"], {}).get("base_uom_id")

            stock_line = {
                "item_id": ln["item_id"],
                "uom_id": ln["uom_id"],
                "accepted_qty": ln["accepted_qty"],
                "unit_price": ln.get("unit_price"),
                "doc_row_id": ln.get("doc_row_id"),
                "base_uom_id": base_uom_id  # ✅ For UOM conversion in stock engine only
            }
            stock_lines.append(stock_line)

        return stock_lines
    # def _calculate_total_amount(self, lines: List[Dict]) -> Decimal:
    #     """Σ(accepted_qty * unit_price) where price is present."""
    #     return sum(
    #         Decimal(str(ln["accepted_qty"])) * Decimal(str(ln["unit_price"]))
    #         for ln in lines if ln.get("unit_price") is not None
    #     )

    def _calculate_total_amount(self, company_id: int, lines: List[Dict]) -> Decimal:
        """
        Calculate total amount with proper UOM conversion.

        ✅ ERP STANDARD:
          - If UOM is different from base UOM, convert quantity first
          - Total = base_qty × unit_price (where unit_price is per base UOM)

        Example:
          Line 1: 1 Piece @ $5/Piece = $5
          Line 2: 1 Box @ $2/Piece (1 Box = 12 Pieces) = 12 × $2 = $24
          Total: $5 + $24 = $29
        """
        from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing

        total = Decimal("0")

        for ln in lines:
            unit_price = ln.get("unit_price")
            if unit_price is None:
                continue

            accepted_qty = Decimal(str(ln["accepted_qty"]))
            unit_price_dec = Decimal(str(unit_price))
            uom_id = ln.get("uom_id")
            item_id = ln["item_id"]

            # Get item details for base UOM
            item_details = self.repo.get_item_details_batch(company_id, [item_id])
            item_detail = item_details.get(item_id, {})
            base_uom_id = item_detail.get("base_uom_id")

            if not base_uom_id:
                # If no base UOM, just use transaction qty (shouldn't happen for stock items)
                line_total = accepted_qty * unit_price_dec
                logging.warning(
                    f"Item {item_id} has no base_uom_id. "
                    f"Using transaction qty for total: {accepted_qty} × ${unit_price_dec} = ${line_total}"
                )
                total += line_total
                continue

            # Check if UOM conversion is needed
            if not uom_id or uom_id == base_uom_id:
                # No conversion needed
                line_total = accepted_qty * unit_price_dec
                logging.debug(
                    f"Item {item_id}: No UOM conversion. "
                    f"{accepted_qty} × ${unit_price_dec} = ${line_total}"
                )
            else:
                # Convert quantity to base UOM
                try:
                    base_qty_float, factor = to_base_qty(
                        qty=accepted_qty,
                        item_id=item_id,
                        uom_id=uom_id,
                        base_uom_id=base_uom_id,
                        strict=True
                    )
                    base_qty = Decimal(str(base_qty_float))

                    # ✅ Calculate total using base quantity
                    line_total = base_qty * unit_price_dec

                    logging.debug(
                        f"Item {item_id}: UOM conversion applied. "
                        f"Txn: {accepted_qty} UOM#{uom_id}, "
                        f"Base: {base_qty} UOM#{base_uom_id}, "
                        f"Rate: ${unit_price_dec}/base_unit, "
                        f"Total: ${line_total}"
                    )
                except UOMFactorMissing:
                    # Fallback: use transaction qty if conversion fails
                    line_total = accepted_qty * unit_price_dec
                    logging.error(
                        f"UOM conversion failed for item {item_id}, uom {uom_id}. "
                        f"Using transaction qty: {accepted_qty} × ${unit_price_dec} = ${line_total}"
                    )

            total += line_total

        logging.info(f"Calculated total amount: ${total}")
        return total

    # ---- public API ----------------------------------------------------------


    def create_purchase_receipt(self, *, payload: PurchaseReceiptCreate,
                                context: AffiliationContext) -> PurchaseReceipt:
        """Create a NORMAL purchase receipt."""
        try:
            company_id, branch_id = resolve_company_branch_and_scope(
                context=context,
                payload_company_id=payload.company_id,
                branch_id=payload.branch_id or getattr(context, "branch_id", None),
                get_branch_company_id=self.repo.get_branch_company_id,
                require_branch=True,
            )
            # --- GATE 1: VALIDATION AT CREATION (for UX) ---
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=payload.posting_date,
                company_id=company_id,
            )
            logging.info("✅ Posting date validation passed during creation.")

            # Validate header
            self._validate_header(company_id, branch_id, payload.supplier_id, payload.warehouse_id)

            # Validate and normalize lines
            lines_data = [ln.model_dump() for ln in payload.items]
            # normalized_lines = self._validate_and_normalize_lines(company_id, lines_data)

            normalized_lines = self._validate_and_normalize_lines(company_id, lines_data,
                                                                  is_return=False)  # ✅ ADD is_return=False

            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            total_amount = self._calculate_total_amount(company_id, normalized_lines)

            # ✅ CORRECTED: Create PurchaseReceiptItem without base_uom_id
            pr_items = []
            for ln in normalized_lines:
                item_data = {
                    "item_id": ln["item_id"],
                    "uom_id": ln["uom_id"],
                    "received_qty": ln["received_qty"],
                    "accepted_qty": ln["accepted_qty"],
                    "unit_price": ln.get("unit_price"),
                    "remarks": ln.get("remarks")
                }
                # Add doc_row_id only if it exists
                if "doc_row_id" in ln:
                    item_data["doc_row_id"] = ln["doc_row_id"]

                pr_items.append(PurchaseReceiptItem(**item_data))

            # Create normal receipt
            pr = PurchaseReceipt(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=payload.supplier_id,
                warehouse_id=payload.warehouse_id,
                code=code,
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                is_return=False,
                return_against_id=None,
                remarks=payload.remarks,
                total_amount=total_amount,

                # total_amount=self._calculate_total_amount(normalized_lines),
                items=pr_items,  # ✅ Use the properly created items
            )

            self.repo.save(pr)
            self.s.commit()
            logging.info(f"Created purchase receipt {pr.code} (ID: {pr.id})")
            return pr

        except Exception as e:
            self.s.rollback()
            logging.error(f"Failed to create purchase receipt: {str(e)}")
            raise

    def create_purchase_return(self, *, original_receipt_id: int, payload: PurchaseReturnCreate,
                               context: AffiliationContext) -> PurchaseReceipt:
        """Create a Purchase Return against an original submitted receipt."""
        try:
            logging.info(
                f"🔄 CREATE PURCHASE RETURN STARTED: receipt_id={original_receipt_id}, user_id={context.user_id}")
            logging.info(f"📦 PAYLOAD: branch_id={payload.branch_id}, items_count={len(payload.items)}")

            # Get original receipt
            original_pr = self.repo.get_original_for_return(original_receipt_id)
            if not original_pr:
                logging.error(f"❌ ORIGINAL RECEIPT NOT FOUND: {original_receipt_id}")
                raise V.BizValidationError(V.ERR_RETURN_AGAINST_INVALID)

            logging.info(
                f"📦 FOUND ORIGINAL RECEIPT: ID={original_pr.id}, Code={original_pr.code}, Company={original_pr.company_id}, Status={original_pr.doc_status}")

            # Verify the original receipt belongs to user's company
            if original_pr.company_id != context.company_id:
                logging.error(
                    f"❌ COMPANY MISMATCH: User company={context.company_id}, Receipt company={original_pr.company_id}")
                raise V.BizValidationError("Original receipt does not belong to your company.")

                # --- GATE 1: VALIDATION AT CREATION (for UX) ---
            PostingDateValidator.validate_return_against_original(
                s=self.s,
                current_posting_date=payload.posting_date,
                original_document_date=original_pr.posting_date,
                company_id=original_pr.company_id,
            )
            logging.info("✅ Purchase return posting date validation passed during creation.")

            # Smart branch resolution
            if payload.branch_id is not None:
                branch_id = payload.branch_id
                company_id = self.repo.get_branch_company_id(branch_id)
                if not company_id:
                    logging.error(f"❌ INVALID BRANCH: {branch_id}")
                    raise V.BizValidationError("Invalid branch_id provided.")

                if company_id != original_pr.company_id:
                    logging.error(
                        f"❌ BRANCH COMPANY MISMATCH: Branch company={company_id}, Receipt company={original_pr.company_id}")
                    raise V.BizValidationError("Branch does not belong to the same company as the original receipt.")
                logging.info(f"🏢 USING PAYLOAD BRANCH: {branch_id}")
            else:
                company_id = original_pr.company_id
                branch_id = original_pr.branch_id
                logging.info(f"🏢 USING ORIGINAL RECEIPT BRANCH: {branch_id}")

            # Ensure user has access
            ensure_scope_by_ids(
                context=context,
                target_company_id=company_id,
                target_branch_id=branch_id,
            )
            logging.info(f"✅ ACCESS GRANTED: company_id={company_id}, branch_id={branch_id}")

            # Validate return items
            logging.info(f"🔍 STARTING ITEM VALIDATION for {len(payload.items)} items")
            validated_return_items = self._validate_return_items(original_pr, payload.items)
            logging.info(f"✅ ITEM VALIDATION COMPLETED: {len(validated_return_items)} items validated")

            # Generate return document code
            code = self._generate_or_validate_code(company_id, branch_id, payload.code)
            logging.info(f"📝 GENERATED RETURN CODE: {code}")

            # Calculate total with UOM conversion
            total_amount = self._calculate_total_amount(company_id, validated_return_items)
            logging.info(f"💰 CALCULATED TOTAL AMOUNT: {total_amount}")

            # Create return items
            return_pr_items = []
            for ln in validated_return_items:
                item_data = {
                    "item_id": ln["item_id"],
                    "uom_id": ln["uom_id"],
                    "received_qty": ln["received_qty"],
                    "accepted_qty": ln["accepted_qty"],
                    "unit_price": ln.get("unit_price"),
                    "remarks": ln.get("remarks"),
                    "return_against_item_id": ln.get("return_against_item_id")
                }
                return_pr_items.append(PurchaseReceiptItem(**item_data))
                logging.info(f"📋 CREATED RETURN ITEM: item_id={ln['item_id']}, qty={ln['accepted_qty']}")

            # Create return receipt
            return_pr = PurchaseReceipt(
                company_id=company_id,
                branch_id=branch_id,
                created_by_id=context.user_id,
                supplier_id=original_pr.supplier_id,
                warehouse_id=original_pr.warehouse_id,
                code=code,
                posting_date=payload.posting_date,
                doc_status=DocStatusEnum.DRAFT,
                is_return=True,
                return_against_id=original_pr.id,
                remarks=payload.remarks,
                total_amount=total_amount,
                items=return_pr_items,
            )

            self.repo.save(return_pr)
            self.s.commit()

            logging.info(
                f"✅ PURCHASE RETURN CREATED SUCCESSFULLY: ID={return_pr.id}, Code={return_pr.code}, Against={original_pr.code}")
            return return_pr

        except Exception as e:
            logging.error(f"❌ FAILED TO CREATE PURCHASE RETURN: {str(e)}")
            self.s.rollback()
            raise

    def _validate_return_items(self, original_pr: PurchaseReceipt, return_items: List[PurchaseReturnItemCreate]) -> \
    List[Dict]:
        # ✅ ADD COMPREHENSIVE DEBUG LOGGING
        logging.info(f"🔍 VALIDATE RETURN ITEMS DEBUG:")
        logging.info(f"   Original Receipt ID: {original_pr.id}")
        logging.info(f"   Original Receipt Code: {original_pr.code}")
        logging.info(
            f"   Original Receipt Items: {[(item.id, item.item_id, item.accepted_qty) for item in original_pr.items]}")
        logging.info(
            f"   Return Items Requested: {[(item.original_item_id, item.return_qty) for item in return_items]}")

        original_items_map = {item.id: item for item in original_pr.items}
        original_item_ids = [ln.original_item_id for ln in return_items]

        logging.info(f"   Looking for original_item_ids: {original_item_ids}")
        logging.info(f"   Available item IDs in original receipt: {list(original_items_map.keys())}")

        previously_returned_qtys = self.repo.get_returned_quantities_for_items(original_item_ids)
        logging.info(f"   Previously returned quantities: {previously_returned_qtys}")

        validated_lines_data = []
        for line in return_items:
            original_item = original_items_map.get(line.original_item_id)

            if not original_item:
                logging.error(
                    f"❌ ITEM NOT FOUND: original_item_id {line.original_item_id} not found in receipt {original_pr.id}")
                logging.error(f"   Available item IDs: {list(original_items_map.keys())}")
                raise V.BizValidationError(V.ERR_RETURN_ITEM_NOT_FOUND)

            previously_returned = previously_returned_qtys.get(line.original_item_id, Decimal("0"))
            balance_qty = Decimal(str(original_item.accepted_qty)) - previously_returned

            logging.info(
                f"   Item {line.original_item_id}: Original Qty: {original_item.accepted_qty}, Previously Returned: {previously_returned}, Balance: {balance_qty}, Return Qty: {line.return_qty}")

            if line.return_qty > balance_qty:
                logging.error(
                    f"❌ QUANTITY EXCEEDED: Return qty {line.return_qty} > balance qty {balance_qty} for item {line.original_item_id}")
                raise V.BizValidationError(V.ERR_RETURN_QTY_EXCEEDED)

            negative_qty = -abs(line.return_qty)
            validated_lines_data.append({
                "item_id": original_item.item_id,
                "uom_id": original_item.uom_id,
                "unit_price": original_item.unit_price,
                "received_qty": negative_qty,
                "accepted_qty": negative_qty,
                "remarks": line.remarks,
                "return_against_item_id": line.original_item_id,
            })

            logging.info(f"✅ Item {line.original_item_id} validated successfully")

        logging.info(f"🔍 RETURN VALIDATION COMPLETED: {len(validated_lines_data)} items validated")
        return validated_lines_data
    def get_stock_intents_data(self, pr: PurchaseReceipt) -> List[Dict]:
        """Prepare data for stock engine with base_uom_id for UOM conversion."""
        stock_lines = []
        for item in pr.items:
            # Get base_uom_id for UOM conversion
            item_details = self.repo.get_item_details_batch(pr.company_id, [item.item_id])
            base_uom_id = item_details.get(item.item_id, {}).get("base_uom_id")

            stock_line = {
                "item_id": item.item_id,
                "uom_id": item.uom_id,
                "accepted_qty": item.accepted_qty,
                "unit_price": item.unit_price,
                "doc_row_id": item.id,
                "base_uom_id": base_uom_id  # ✅ For UOM conversion in stock engine
            }
            stock_lines.append(stock_line)

        return stock_lines
    def update_purchase_receipt(self, *, receipt_id: int, payload: PurchaseReceiptUpdate, context: AffiliationContext) -> PurchaseReceipt:
        try:
            pr = self._get_validated_receipt(receipt_id, context, for_update=True)
            V.guard_draft_only(pr.doc_status)

            header_changed = False
            if payload.supplier_id is not None and payload.supplier_id != pr.supplier_id:
                pr.supplier_id = payload.supplier_id
                header_changed = True
            if payload.warehouse_id is not None and payload.warehouse_id != pr.warehouse_id:
                pr.warehouse_id = payload.warehouse_id
                header_changed = True

            if header_changed:
                self._validate_header(pr.company_id, pr.branch_id, pr.supplier_id, pr.warehouse_id)

            if payload.posting_date:
                pr.posting_date = payload.posting_date
            if payload.remarks is not None:
                pr.remarks = payload.remarks

            if payload.items is not None:
                lines_data = [ln.model_dump() for ln in payload.items]
                self._validate_and_normalize_lines(pr.company_id, lines_data)
                self.repo.sync_lines(pr, lines_data)
                pr.total_amount = self._calculate_total_amount(lines_data)

            self.repo.save(pr)
            self.s.commit()
            return pr

        except Exception:
            self.s.rollback()
            raise

    def _get_doc_type_id_or_400(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            # make it a clean 400 so the endpoint returns a business error, not a 500
            raise V.BizValidationError(f"DocumentType '{code}' not found. Seed the Document Types table.")
        return dt

    @staticmethod
    def _combine_date(posting_date_val: date | datetime) -> datetime:
        """Return a proper datetime with time component for stock posting."""
        return resolve_posting_dt(posting_date_val)

    def guard_purchase_receipt_submittable(self, pr: PurchaseReceipt) -> None:
        """
        Purchase-specific submission guard that works with your existing global guard.

        ✅ BUSINESS RULES:
          - Uses existing global guard for basic DRAFT check
          - Adds purchase-specific return validation
          - Maintains compatibility with other document types
          - Prevents double processing
          - Validates return references
        """
        # ✅ First use existing global guard (for DRAFT check)
        V.guard_submittable_state(pr.doc_status)

        # ✅ Then add purchase-specific validations
        if pr.is_return:
            # Prevent double processing of returns
            if pr.doc_status == DocStatusEnum.RETURNED:
                raise V.BizValidationError("Purchase return has already been processed.")

            # Validate return has original receipt reference
            if not pr.return_against_id:
                raise V.BizValidationError("Purchase return must reference an original receipt.")
        else:
            # Normal receipt specific validations
            if pr.doc_status == DocStatusEnum.SUBMITTED:
                raise V.BizValidationError("Purchase receipt has already been submitted.")


    def submit_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        """
        Submit a Purchase Receipt (either normal receipt or return).

        ✅ UNIFIED FLOW:
        1. Detect if it's a return (is_return=True)
        2. Use appropriate intent builder (receipt vs return)
        3. Set final status (SUBMITTED for receipt, RETURNED for return)
        4. Process stock, BIN, and GL entries atomically

        ✅ BUSINESS RULES:
        - Normal receipts → SUBMITTED status
        - Returns → RETURNED status
        - Prevents double processing
        - Validates return references
        - Handles UOM conversions correctly
        """
        from sqlalchemy import and_, select, func
        import logging

        try:
            # ---- 1) READ PHASE (no locks) ---------------------------------------
            logging.info("PR submit: start receipt_id=%s", receipt_id)

            pr = self._get_validated_receipt(receipt_id, context, for_update=False)
            # ✅ ADD: Fiscal period validation at submission
            PostingDateValidator.validate_standalone_document(
                s=self.s,
                posting_date=pr.posting_date,
                company_id=pr.company_id,
            )
            # ✅ Use the specialized purchase receipt guard
            self.guard_purchase_receipt_submittable(pr)

            V.validate_list_not_empty(pr.items, "items for submission")
            self._validate_header(pr.company_id, pr.branch_id, pr.supplier_id, pr.warehouse_id)

            # ✅ Get company timezone
            from app.common.timezone.service import get_company_timezone
            company_tz = get_company_timezone(self.s, pr.company_id)
            logging.info("PR submit: Using company timezone: %s", company_tz)

            # ✅ Determine document type based on is_return flag
            is_return_doc = pr.is_return
            doc_type_code = "PURCHASE_RETURN" if is_return_doc else "PURCHASE_RECEIPT"

            logging.info(
                f"PR submit: Processing {'RETURN' if is_return_doc else 'RECEIPT'} | "
                f"pr_id={pr.id} code={pr.code} return_against={pr.return_against_id if is_return_doc else 'N/A'}"
            )

            item_ids = [item.item_id for item in pr.items]
            item_details = self.repo.get_item_details_batch(pr.company_id, item_ids)
            lines_snap = [{
                "item_id": i.item_id,
                "uom_id": i.uom_id,
                "received_qty": i.received_qty,
                "accepted_qty": i.accepted_qty,
                "unit_price": i.unit_price,
                "doc_row_id": i.id,
                "base_uom_id": item_details.get(i.item_id, {}).get("base_uom_id")
            } for i in pr.items]

            logging.info("PR submit: Raw accepted_qty values: %s", [i.accepted_qty for i in pr.items])
            logging.info("PR submit: UOM info - %s", [{"item": i.item_id, "uom": i.uom_id} for i in pr.items])
            norm = self._validate_and_normalize_lines(pr.company_id, lines_snap, is_return_doc)  # <-- CHANGED

            # norm = self._validate_and_normalize_lines(pr.company_id, lines_snap)

            # ✅ For returns, quantities should be negative
            if is_return_doc:
                # Ensure all quantities are negative
                for ln in norm:
                    if Decimal(str(ln.get("accepted_qty") or 0)) > 0:
                        logging.warning(
                            f"Return document has positive qty for item {ln['item_id']}. "
                            "This should have been negative."
                        )
                stock_lines = [ln for ln in norm if Decimal(str(ln.get("accepted_qty") or 0)) != 0]
            else:
                # Normal receipt: only positive quantities
                stock_lines = [ln for ln in norm if Decimal(str(ln.get("accepted_qty") or 0)) > 0]

            V.validate_list_not_empty(stock_lines, "stock items for submission")

            doc_type_id = self._get_doc_type_id_or_400(doc_type_code)

            # ✅ Resolve posting datetime with correct timezone
            posting_dt = resolve_posting_dt(
                pr.posting_date.date() if hasattr(pr.posting_date, "date") else pr.posting_date,
                created_at=pr.created_at,
                tz=company_tz,
                treat_midnight_as_date=True,
            )

            logging.info("PR submit: posting_dt=%s (timezone: %s)", posting_dt, posting_dt.tzinfo)

            # ✅ Build intents based on document type
            if is_return_doc:
                logging.info("PR submit: Building RETURN intents")
                intents = build_intents_for_return(
                    company_id=pr.company_id,
                    branch_id=pr.branch_id,
                    warehouse_id=pr.warehouse_id,
                    posting_dt=posting_dt,
                    doc_type_id=doc_type_id,
                    doc_id=pr.id,
                    lines=[{
                        "uom_id": ln["uom_id"],
                        "item_id": ln["item_id"],
                        "accepted_qty": ln["accepted_qty"],  # Already negative
                        "unit_price": ln["unit_price"],
                        "doc_row_id": ln["doc_row_id"],
                        "base_uom_id": ln.get("base_uom_id")
                    } for ln in stock_lines],
                    session=self.s,
                )
            else:
                logging.info("PR submit: Building RECEIPT intents")
                intents = build_intents_for_receipt(
                    company_id=pr.company_id,
                    branch_id=pr.branch_id,
                    warehouse_id=pr.warehouse_id,
                    posting_dt=posting_dt,
                    doc_type_id=doc_type_id,
                    doc_id=pr.id,
                    lines=[{
                        "uom_id": ln["uom_id"],
                        "item_id": ln["item_id"],
                        "accepted_qty": ln["accepted_qty"],
                        "unit_price": ln["unit_price"],
                        "doc_row_id": ln["doc_row_id"],
                        "base_uom_id": ln.get("base_uom_id")
                    } for ln in stock_lines],
                    session=self.s,
                )

            if not intents:
                raise V.BizValidationError("No stock intents were generated from lines.")

            pairs: Set[Tuple[int, int]] = {(i.item_id, i.warehouse_id) for i in intents}
            logging.info(
                "PR submit: snapshot ok | pr_id=%s doc_type_id=%s posting_dt=%s intents=%s pairs=%s",
                pr.id, doc_type_id, posting_dt.isoformat(), len(intents), len(pairs)
            )

            # Backdating check
            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = self.s.query(func.count()).select_from(StockLedgerEntry).filter(
                    StockLedgerEntry.company_id == pr.company_id,
                    StockLedgerEntry.item_id == item_id,
                    StockLedgerEntry.warehouse_id == wh_id,
                    (
                            (StockLedgerEntry.posting_date > posting_dt.date()) |
                            and_(
                                StockLedgerEntry.posting_date == posting_dt.date(),
                                StockLedgerEntry.posting_time > posting_dt,
                            )
                    ),
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                )
                return (q.scalar() or 0) > 0

            is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
            logging.info("PR submit: backdated=%s | pairs=%s", is_backdated, list(pairs))

            # ---- 2) ATOMIC WRITE PHASE (SAVEPOINT) ------------------------------
            with self.s.begin_nested():
                pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)

                # ✅ Re-validate under lock using the helper
                self.guard_purchase_receipt_submittable(pr_locked)

                # 2a) SLEs under advisory locks
                sle_written = 0
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        logging.info("PR submit: Final intent for SLE before append: %s", {
                            "item_id": intent.item_id,
                            "warehouse_id": intent.warehouse_id,
                            "actual_qty": intent.actual_qty,
                            "incoming_rate": intent.incoming_rate,
                            "outgoing_rate": intent.outgoing_rate,
                            "doc_id": intent.doc_id,
                            "is_return": is_return_doc,
                            "meta": getattr(intent, "meta", {}),
                        })

                        # ✅ Pass timezone and batch index
                        sle = append_sle(
                            self.s,
                            intent,
                            created_at_hint=pr_locked.created_at,
                            tz_hint=company_tz,
                            batch_index=idx,
                        )
                        sle_written += 1
                        logging.info(
                            "PR submit: SLE appended | pr_id=%s sle_id=%s sle_written=%s type=%s",
                            pr_locked.id, sle.id, sle_written, 'RETURN' if is_return_doc else 'RECEIPT'
                        )

                if sle_written != len(intents):
                    raise RuntimeError(f"SLE append mismatch (expected {len(intents)}, wrote {sle_written}).")
                logging.info("PR submit: SLE appended | pr_id=%s sle_written=%s", pr_locked.id, sle_written)

                # 2b) Backdated replay
                if is_backdated:
                    for item_id, wh_id in pairs:
                        logging.info("PR submit: Starting replay for item=%s, wh=%s", item_id, wh_id)
                        repost_from(
                            s=self.s,
                            company_id=pr_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set()
                        )
                    logging.info("PR submit: replay done for pairs=%s", list(pairs))

                # 2c) Derive BINs
                bins_updated = 0
                for item_id, wh_id in pairs:
                    logging.info("PR submit: Deriving bin for item=%s, wh=%s", item_id, wh_id)
                    bin_obj = derive_bin(self.s, pr_locked.company_id, item_id, wh_id)
                    bins_updated += 1

                logging.info("PR submit: bins derived | pr_id=%s bins_updated=%s", pr_locked.id, bins_updated)

                # 2d) GL post (AUTO) — PostingService
                from app.application_accounting.engine.posting_service import PostingService, PostingContext
                from app.application_accounting.chart_of_accounts.models import PartyTypeEnum

                acc_lines = [{"accepted_qty": ln["accepted_qty"], "unit_price": ln["unit_price"]} for ln in stock_lines]

                # ✅ IMPROVEMENT: Calculate total stock value for better GL handling
                total_stock_value = sum(
                    abs(Decimal(str(ln["accepted_qty"]))) * Decimal(str(ln["unit_price"]))
                    for ln in stock_lines
                )

                # ✅ Use appropriate template for return vs receipt
                if is_return_doc:
                    # Purchase Receipt returns are ALWAYS against receipts (GRNI), not invoices
                    template_code = "PURCHASE_RETURN_GRNI"  # Always use GRNI template for receipt returns
                    amount_source_key = "RETURN_STOCK_VALUE"
                    logging.info("PR submit: Using PURCHASE_RETURN_GRNI template (receipt return)")
                else:
                    template_code = "PURCHASE_RECEIPT_GRNI"  # Normal purchase receipt
                    amount_source_key = "INVENTORY_PURCHASE_COST"
                    logging.info("PR submit: Using PURCHASE_RECEIPT_GRNI template (normal receipt)")

                logging.info(
                    "PR submit: GL posting with template=%s, stock_value=%.2f",
                    template_code, total_stock_value
                )

                ctx = PostingContext(
                    company_id=pr_locked.company_id,
                    branch_id=pr_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=pr_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"{'Purchase Return' if is_return_doc else 'Purchase Receipt'} {pr_locked.code}",
                    template_code=template_code,
                    payload={
                        "receipt_lines": acc_lines,
                        "is_return": is_return_doc,
                        # ✅ CORRECTED: Use appropriate amount source based on template
                        amount_source_key: total_stock_value,
                    },
                    runtime_accounts={},
                    party_id=pr_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                )
                PostingService(self.s).post(ctx)
                logging.info("PR submit: GL posted | pr_id=%s lines=%s template=%s",
                             pr_locked.id, len(acc_lines), template_code)


                # 2e) Mark final status
                # ✅ Returns get RETURNED status, normal receipts get SUBMITTED
                final_status = DocStatusEnum.RETURNED if is_return_doc else DocStatusEnum.SUBMITTED
                pr_locked.doc_status = final_status
                self.repo.save(pr_locked)
                logging.info(
                    "PR submit: status -> %s | pr_id=%s code=%s",
                    final_status.value, pr_locked.id, pr_locked.code
                )

            # ---- 3) COMMIT OUTER TX ---------------------------------------------
            logging.info("PR submit: committing outer transaction for pr_id=%s", pr.id)
            self.s.commit()

            # ---- 4) Post-commit SLE sanity --------------------------------------
            try:
                cnt = self.s.execute(
                    select(func.count()).select_from(StockLedgerEntry).where(
                        StockLedgerEntry.company_id == pr.company_id,
                        StockLedgerEntry.doc_type_id == doc_type_id,
                        StockLedgerEntry.doc_id == pr.id,
                        StockLedgerEntry.is_cancelled == False,
                    )
                ).scalar()
                logging.info("DEBUG post-commit: SLE count for PR id=%s -> %s", pr.id, cnt)
            except Exception:
                logging.exception("DEBUG post-commit: failed to count SLE for PR")

            logging.info(
                "PR submit: success | pr_id=%s code=%s status=%s",
                pr.id, pr.code, final_status.value
            )
            return pr

        except Exception:
            logging.exception("PR submit: FAILED (rolled back) | receipt_id=%s", receipt_id)
            self.s.rollback()
            raise
    # -------------------------------------------------------------------------
    # CANCEL — Reverse Stock + Accounting
    # -------------------------------------------------------------------------

    def cancel_purchase_receipt(self, *, receipt_id: int, context: AffiliationContext) -> PurchaseReceipt:
        """
        CANCEL flow:
          1) Read phase: validate; collect SLEs (not cancelled, not reversals).
          2) Write phase (SAVEPOINT): lock PR, set CANCELLED, write reversal SLEs under advisory locks.
          3) Commit outer transaction.
          4) Post-commit stock maintenance:
               - backdated -> replay valuation forward from earliest SLE posting_time
               - else      -> derive BINs
          5) Accounting reversal via PostingService.cancel (auto JE).
        """
        try:
            logging.info("PR cancel: start receipt_id=%s", receipt_id)

            # ---- 1) READ PHASE ----------------------------------------------------
            pr = self._get_validated_receipt(receipt_id, context, for_update=False)

            V.guard_cancellable_state(pr.doc_status)

            doc_type_id = self._get_doc_type_id_or_400("PURCHASE_RECEIPT")

            sle_rows = (
                self.s.query(
                    StockLedgerEntry.id,
                    StockLedgerEntry.item_id,
                    StockLedgerEntry.warehouse_id,
                    StockLedgerEntry.posting_time,
                )
                .filter(
                    StockLedgerEntry.company_id == pr.company_id,
                    StockLedgerEntry.doc_type_id == doc_type_id,
                    StockLedgerEntry.doc_id == pr.id,
                    StockLedgerEntry.is_cancelled == False,  # noqa: E712
                    StockLedgerEntry.is_reversal == False,
                )
                .order_by(
                    StockLedgerEntry.posting_date.asc(),
                    StockLedgerEntry.posting_time.asc(),
                    StockLedgerEntry.id.asc(),
                )
                .all()
            )

            # If no SLEs -> still cancel PR and reverse GL.
            if not sle_rows:
                self.s.rollback()
                with self.s.begin():
                    pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)
                    V.guard_cancellable_state(pr_locked.doc_status)
                    pr_locked.doc_status = DocStatusEnum.CANCELLED
                    self.repo.save(pr_locked)

                # Accounting reversal (separate tx)
                with self.s.begin():
                    # FIX: avoid midnight collisions for accounting reversal timestamp
                    acct_posting_dt = resolve_posting_dt(
                        pr_locked.posting_date if not hasattr(pr_locked.posting_date, "date") else pr_locked.posting_date,
                        created_at=getattr(pr_locked, "created_at", None),
                        tz=timezone(timedelta(hours=3)),           # TODO: plug company/system TZ
                        treat_midnight_as_date=True,
                    )
                    PostingService(self.s).cancel(
                        PostingContext(
                            company_id=pr_locked.company_id,
                            branch_id=pr_locked.branch_id,
                            source_doctype_id=doc_type_id,
                            source_doc_id=pr_locked.id,
                            posting_date=acct_posting_dt,            # FIX: tz-aware, non-midnight
                            created_by_id=context.user_id,
                            is_auto_generated=True,
                            entry_type=None,
                            remarks=f"Cancel Purchase Receipt {pr_locked.id}",
                            template_code=None,
                            payload={},
                            runtime_accounts={},
                            party_id=pr_locked.supplier_id,
                            party_type=PartyTypeEnum.SUPPLIER,
                        )
                    )

                logging.info("PR cancel: success (no stock effects) id=%s code=%s", pr.id, pr.code)
                return pr_locked

            pairs: Set[Tuple[int, int]] = {(r.item_id, r.warehouse_id) for r in sle_rows}
            start_dt: datetime = min(r.posting_time for r in sle_rows)

            # FIX: ensure tz-aware start_dt for consistent comparisons
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)

            def _has_future_sle(item_id: int, wh_id: int) -> bool:
                q = (
                    self.s.query(StockLedgerEntry.id)
                    .filter(
                        StockLedgerEntry.company_id == pr.company_id,
                        StockLedgerEntry.item_id == item_id,
                        StockLedgerEntry.warehouse_id == wh_id,
                        (
                            (StockLedgerEntry.posting_date > start_dt.date())
                            | and_(
                                StockLedgerEntry.posting_date == start_dt.date(),
                                StockLedgerEntry.posting_time > start_dt,
                            )
                        ),
                        StockLedgerEntry.is_cancelled == False,  # noqa: E712
                    )
                    .limit(1)
                )
                return self.s.query(q.exists()).scalar()

            is_backdated = any(_has_future_sle(i, w) for (i, w) in pairs)
            logging.info("PR cancel: backdated=%s | pairs=%s", is_backdated, list(pairs))

            # Close any implicit tx before the write phase
            self.s.rollback()

            # ---- 2) WRITE PHASE (SAVEPOINT) ---------------------------------------
            with self.s.begin_nested():
                pr_locked = self._get_validated_receipt(receipt_id, context, for_update=True)
                V.guard_cancellable_state(pr_locked.doc_status)

                pr_locked.doc_status = DocStatusEnum.CANCELLED
                self.repo.save(pr_locked)

                # Reverse exactly the PR’s SLEs under advisory locks
                with lock_pairs(self.s, pairs):
                    originals = (
                        self.s.query(StockLedgerEntry)
                        .filter(
                            StockLedgerEntry.company_id == pr_locked.company_id,
                            StockLedgerEntry.doc_type_id == doc_type_id,
                            StockLedgerEntry.doc_id == pr_locked.id,
                            StockLedgerEntry.is_cancelled == False,  # noqa: E712
                            StockLedgerEntry.is_reversal == False,
                        )
                        .order_by(
                            StockLedgerEntry.posting_date.asc(),
                            StockLedgerEntry.posting_time.asc(),
                            StockLedgerEntry.id.asc(),
                        )
                        .all()
                    )
                    for original in originals:
                        # cancel_sle() already pushes reversal by +1µs after original
                        cancel_sle(self.s, original)

            # ---- 3) COMMIT OUTER TX BEFORE MAINTENANCE ----------------------------
            self.s.commit()

            # ---- 4) POST-COMMIT STOCK MAINTENANCE ---------------------------------
            if is_backdated:
                with self.s.begin():
                    for item_id, wh_id in pairs:
                        repost_from(
                            s=self.s,
                            company_id=pr.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=start_dt,  # FIX: tz-aware earliest original time
                        )
                logging.info("PR cancel: replay done for pairs=%s", list(pairs))
            else:
                with self.s.begin():
                    for item_id, wh_id in pairs:
                        derive_bin(self.s, pr.company_id, item_id, wh_id)
                logging.info("PR cancel: bins derived for pairs=%s", list(pairs))

            # ---- 5) ACCOUNTING REVERSAL -------------------------------------------
            with self.s.begin():
                # FIX: avoid midnight collisions and ensure tz-aware reversal timestamp
                acct_posting_dt = resolve_posting_dt(
                    pr.posting_date if not hasattr(pr.posting_date, "date") else pr.posting_date,
                    created_at=getattr(pr, "created_at", None),
                    tz=timezone(timedelta(hours=3)),               # TODO: plug company/system TZ
                    treat_midnight_as_date=True,
                )
                PostingService(self.s).cancel(
                    PostingContext(
                        company_id=pr.company_id,
                        branch_id=pr.branch_id,
                        source_doctype_id=doc_type_id,
                        source_doc_id=pr.id,
                        posting_date=acct_posting_dt,                # FIX
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=None,
                        remarks=f"Cancel Purchase Receipt {pr.id}",
                        template_code=None,
                        payload={},
                        runtime_accounts={},
                        party_id=pr.supplier_id,
                        party_type=PartyTypeEnum.SUPPLIER,
                    )
                )

            logging.info("PR cancel: success id=%s code=%s", pr.id, pr.code)
            return pr

        except Exception:
            logging.exception("PR cancel: FAILED", extra={"receipt_id": receipt_id})
            self.s.rollback()
            raise
