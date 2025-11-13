# # app/application_buying/invoice_service.py

from __future__ import annotations
from typing import Optional, List, Dict, Tuple, Set
from decimal import Decimal
import logging

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound, Conflict

from config.database import db
from app.application_buying.schemas import (
    PurchaseInvoiceCreate, PurchaseInvoiceUpdate
)
from app.application_buying.repository.invoice_repo import PurchaseInvoiceRepository
from app.application_buying.models import PurchaseInvoice, PurchaseInvoiceItem
from app.application_stock.stock_models import DocStatusEnum, DocumentType, StockLedgerEntry
from app.application_stock.engine.posting_clock import resolve_posting_dt
from app.application_stock.engine.handlers.purchase import (
    build_intents_for_receipt, build_intents_for_return
)
from app.application_stock.engine.locks import lock_pairs
from app.application_stock.engine.sle_writer import append_sle, cancel_sle
from app.application_stock.engine.replay import repost_from
from app.application_stock.engine.bin_derive import derive_bin
from app.application_accounting.chart_of_accounts.models import FiscalYear
from app.application_accounting.engine.posting_service import PostingService, PostingContext
from app.application_accounting.chart_of_accounts.models import PartyTypeEnum
from app.business_validation.posting_date_validation import PostingDateValidator
from app.business_validation import item_validation as V

from app.security.rbac_guards import resolve_company_branch_and_scope, ensure_scope_by_ids
from app.security.rbac_effective import AffiliationContext
logger = logging.getLogger(__name__)

class PurchaseInvoiceService:
    PREFIX = "PINV"

    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session
        self.repo = PurchaseInvoiceRepository(self.s)

    def _generate_or_validate_code(self, company_id: int, branch_id: int, code: Optional[str]) -> str:
        from app.common.generate_code.service import generate_next_code, ensure_manual_code_is_next_and_bump
        if code:
            c = code.strip()
            if self.repo.code_exists(company_id, branch_id, c):
                raise Conflict("Document code already exists in this branch.")
            ensure_manual_code_is_next_and_bump(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id, code=c)
            return c
        return generate_next_code(prefix=self.PREFIX, company_id=company_id, branch_id=branch_id)

    def _validate_header(self, company_id: int, branch_id: int, supplier_id: int, header_wh_id: Optional[int], update_stock: bool) -> None:
        valid_suppliers = self.repo.get_valid_supplier_ids(company_id, [supplier_id])
        V.validate_supplier_is_active(supplier_id in valid_suppliers)
        if update_stock and header_wh_id:
            valid = self.repo.get_transactional_warehouse_ids(company_id, branch_id, [header_wh_id])
            V.validate_warehouse_is_transactional(header_wh_id in valid)

    def _autofill_line_warehouse(self, header_wh_id: Optional[int], update_stock: bool, lines: List[Dict]) -> None:
        if not update_stock or not header_wh_id:
            return
        for ln in lines:
            if ln.get("warehouse_id") is None:
                ln["warehouse_id"] = header_wh_id

    def _validate_and_normalize_lines(self, company_id: int, lines: List[Dict], is_return: bool) -> List[Dict]:
        V.validate_list_not_empty(lines, "items")
        V.validate_unique_items(lines, key="item_id")

        item_ids = [ln["item_id"] for ln in lines]
        details = self.repo.get_item_details_batch(company_id, item_ids)
        work = [{**ln, **details.get(ln["item_id"], {})} for ln in lines]
        V.validate_items_are_active([(ln["item_id"], ln.get("is_active", False)) for ln in work])

        # Stock validation only needed if later we decide update_stock=True
        uoms = [ln["uom_id"] for ln in work if ln.get("uom_id")]
        if uoms:
            existing = self.repo.get_existing_uom_ids(company_id, uoms)
            V.validate_uoms_exist([(u, u in existing) for u in uoms])

        pairs = [(ln["item_id"], ln["uom_id"]) for ln in work if ln.get("uom_id")]
        if pairs:
            compat = self.repo.get_compatible_uom_pairs(company_id, pairs)
            for ln in work:
                if ln.get("uom_id"):
                    ln["uom_ok"] = (ln["item_id"], ln["uom_id"]) in compat
            # Only stock items need compatibility check
            V.validate_item_uom_compatibility([ln for ln in work if ln.get("is_stock_item", False)])

        for ln in work:
            if is_return:
                if Decimal(str(ln["quantity"])) >= 0:
                    raise V.BizValidationError("Return lines must have negative quantity.")
            else:
                V.validate_positive_quantity(ln["quantity"])
            V.validate_non_negative_rate(ln.get("rate"))
            V.validate_positive_price(ln.get("rate"))

        out = []
        for ln in work:
            x = {
                "item_id": ln["item_id"],
                "uom_id": ln.get("uom_id"),
                "quantity": ln["quantity"],
                "rate": ln["rate"],
                "remarks": ln.get("remarks"),
                "receipt_item_id": ln.get("receipt_item_id"),
                "warehouse_id": ln.get("warehouse_id"),
                "return_against_item_id": ln.get("return_against_item_id"),
            }
            out.append(x)
        return out

    def _calculate_total(self, company_id: int, lines: List[Dict]) -> Decimal:
        from app.application_nventory.services.uom_math import to_base_qty, UOMFactorMissing
        total = Decimal("0")
        for ln in lines:
            rate = Decimal(str(ln["rate"]))
            qty = Decimal(str(ln["quantity"]))
            item_id = ln["item_id"]
            uom_id = ln.get("uom_id")
            detail = self.repo.get_item_details_batch(company_id, [item_id]).get(item_id, {})
            base = detail.get("base_uom_id")
            is_stock = detail.get("is_stock_item", False)

            if not is_stock or not base or not uom_id or uom_id == base:
                total += qty * rate
            else:
                try:
                    base_qty_float, _ = to_base_qty(qty=abs(qty), item_id=item_id, uom_id=uom_id, base_uom_id=base, strict=True)
                    base_qty = Decimal(str(base_qty_float))
                    if qty < 0:
                        base_qty = -base_qty
                    total += base_qty * rate
                except UOMFactorMissing:
                    total += qty * rate
        return total

    def _enforce_line_warehouses_if_stock(self, update_stock: bool, lines: List[Dict], header_wh_id: Optional[int]) -> None:
        if not update_stock:
            return
        for ln in lines:
            if ln.get("warehouse_id") is None:
                # try header fallback
                if header_wh_id:
                    ln["warehouse_id"] = header_wh_id
            if ln.get("warehouse_id") is None:
                raise V.BizValidationError("Warehouse is required on each stock line before submit (update_stock=True).")

    def create_purchase_invoice(self, *, payload: PurchaseInvoiceCreate,
                                context: AffiliationContext) -> PurchaseInvoice:
        company_id, branch_id = resolve_company_branch_and_scope(
            context=context,
            payload_company_id=payload.company_id,
            branch_id=payload.branch_id or getattr(context, "branch_id", None),
            get_branch_company_id=self.repo.get_branch_company_id,
            require_branch=True,
        )

        # 👇 Normalize/validate posting datetime exactly like Sales (and USE the result)
        from app.business_validation.posting_date_validation import PostingDateValidator
        norm_dt = PostingDateValidator.validate_standalone_document(
            self.s,
            payload.posting_date,
            company_id,
            created_at=None,
            treat_midnight_as_date=True,
        )

        # if against receipt, ensure receipt exists and matches company/branch/supplier
        if payload.receipt_id:
            r = self.repo.get_receipt_with_items(payload.receipt_id)
            if not r:
                raise V.BizValidationError("Purchase Receipt not found or not submitted.")
            if r.company_id != company_id or r.branch_id != branch_id:
                raise V.BizValidationError("Receipt belongs to a different company/branch.")
            if r.supplier_id != payload.supplier_id:
                raise V.BizValidationError("Invoice supplier must match the receipt supplier.")
            valid_receipt_items = {it.id for it in r.items}
        else:
            valid_receipt_items = set()

        self._validate_header(company_id, branch_id, payload.supplier_id, payload.warehouse_id, payload.update_stock)

        lines = [ln.model_dump() for ln in payload.items]
        # Default per-line warehouses from header ONLY when update_stock=True
        self._autofill_line_warehouse(payload.warehouse_id, payload.update_stock, lines)
        norm = self._validate_and_normalize_lines(company_id, lines, is_return=payload.is_return)

        # if against receipt, enforce rate and quantity limits
        if payload.receipt_id:
            receipt = self.repo.get_receipt_with_items(payload.receipt_id)
            rec_map = {it.id: it for it in receipt.items}

            # compute already billed for each receipt_item_id (excluding CANCELLED)
            rows = self.s.execute(
                select(PurchaseInvoiceItem.receipt_item_id, func.sum(PurchaseInvoiceItem.quantity))
                .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id)
                .where(
                    PurchaseInvoiceItem.receipt_item_id.in_(valid_receipt_items),
                    PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED,
                )
                .group_by(PurchaseInvoiceItem.receipt_item_id)
            ).all()
            billed_map: Dict[int, Decimal] = {rid: (qty or 0) for rid, qty in rows}

            for ln in norm:
                rid = ln.get("receipt_item_id")
                if rid:
                    if rid not in valid_receipt_items:
                        raise V.BizValidationError(
                            f"receipt_item_id {rid} does not belong to receipt {payload.receipt_id}.")
                    rec_it = rec_map[rid]
                    # Rate must match PR rate
                    if ln["rate"] != Decimal(str(rec_it.unit_price or 0)):
                        raise V.BizValidationError(
                            "When billing against receipt, item rate must match the receipt item rate.")
                    # Quantity cannot exceed accepted - already billed
                    already = Decimal(str(billed_map.get(rid, 0)))
                    available = Decimal(str(rec_it.accepted_qty)) - already
                    if Decimal(str(ln["quantity"])) > available:
                        raise V.BizValidationError(
                            f"Over-billing: {ln['quantity']} > available {available} for receipt item {rid}."
                        )

        code = self._generate_or_validate_code(company_id, branch_id, payload.code)
        total = self._calculate_total(company_id, norm)
        pi_items = [PurchaseInvoiceItem(**ln) for ln in norm]

        pi = PurchaseInvoice(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=context.user_id,
            supplier_id=payload.supplier_id,
            warehouse_id=payload.warehouse_id if payload.update_stock else None,
            code=code,
            posting_date=norm_dt,  # 👈 use normalized datetime
            doc_status=DocStatusEnum.DRAFT,
            is_return=payload.is_return,
            return_against_id=payload.return_against_id,
            update_stock=payload.update_stock,
            payable_account_id=payload.payable_account_id,
            mode_of_payment_id=payload.mode_of_payment_id,
            cash_bank_account_id=payload.cash_bank_account_id,
            due_date=payload.due_date,
            receipt_id=payload.receipt_id,
            total_amount=total,
            paid_amount=Decimal("0"),
            outstanding_amount=total,
            remarks=payload.remarks,
            items=pi_items,
        )
        self.repo.save(pi)
        self.s.commit()
        return pi

    def update_purchase_invoice(self, *, invoice_id: int, payload: PurchaseInvoiceUpdate,
                                context: AffiliationContext) -> PurchaseInvoice:
        pi = self.repo.get_by_id(invoice_id, for_update=True)
        if not pi:
            raise NotFound("Purchase Invoice not found.")
        ensure_scope_by_ids(context=context, target_company_id=pi.company_id, target_branch_id=pi.branch_id)

        # Only DRAFT updatable
        from app.business_validation.item_validation import guard_updatable_state
        guard_updatable_state(pi.doc_status)

        # Header updates
        if payload.posting_date is not None:
            from app.business_validation.posting_date_validation import PostingDateValidator
            # 👇 normalize like Sales + Create; then assign normalized
            norm_dt = PostingDateValidator.validate_standalone_document(
                self.s,
                payload.posting_date,
                pi.company_id,
                created_at=None,
                treat_midnight_as_date=True,
            )
            pi.posting_date = norm_dt

        if payload.supplier_id is not None and payload.supplier_id != pi.supplier_id:
            valid = self.repo.get_valid_supplier_ids(pi.company_id, [payload.supplier_id])
            from app.business_validation import item_validation as V
            V.validate_supplier_is_active(payload.supplier_id in valid)
            pi.supplier_id = payload.supplier_id

        if payload.update_stock is not None:
            # You can toggle while draft, but if it becomes True we'll enforce warehouses at submit.
            pi.update_stock = bool(payload.update_stock)

        if payload.warehouse_id is not None:
            if payload.warehouse_id and pi.update_stock:
                valid_wh = self.repo.get_transactional_warehouse_ids(pi.company_id, pi.branch_id,
                                                                     [payload.warehouse_id])
                from app.business_validation import item_validation as V
                V.validate_warehouse_is_transactional(payload.warehouse_id in valid_wh)
            pi.warehouse_id = payload.warehouse_id

        if payload.due_date is not None:
            pi.due_date = payload.due_date

        if payload.remarks is not None:
            pi.remarks = payload.remarks

        # Lines
        if payload.items is not None:
            lines_in = [it.model_dump() for it in payload.items]

            # Direction by pi.is_return
            from decimal import Decimal
            for ln in lines_in:
                if pi.is_return:
                    if Decimal(str(ln["quantity"])) >= 0:
                        raise ValueError("Return Invoice items must have negative quantity.")
                else:
                    if Decimal(str(ln["quantity"])) <= 0:
                        raise ValueError("Normal Invoice items must have positive quantity.")

            from app.business_validation import item_validation as V
            V.validate_list_not_empty(lines_in, "items")
            V.validate_unique_items(lines_in, key="item_id")

            details = self.repo.get_item_details_batch(pi.company_id, [x["item_id"] for x in lines_in])
            V.validate_items_are_active(
                [(x["item_id"], details.get(x["item_id"], {}).get("is_active", False)) for x in lines_in])
            for x in lines_in:
                V.validate_positive_quantity(abs(x["quantity"]))  # magnitude check
                V.validate_non_negative_rate(x.get("rate"))
                V.validate_positive_price(x.get("rate"))

            # If this PI is against a receipt, enforce rate=PR rate and qty <= remaining (excluding this PI itself)
            if pi.receipt_id:
                r = self.repo.get_receipt_with_items(pi.receipt_id)
                if not r:
                    raise V.BizValidationError("Linked Purchase Receipt not found or not submitted.")
                rec_map = {it.id: it for it in r.items}
                valid_receipt_items = set(rec_map.keys())

                # sum billed qty on other invoices
                rows = self.s.execute(
                    select(PurchaseInvoiceItem.receipt_item_id, func.sum(PurchaseInvoiceItem.quantity))
                    .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id)
                    .where(
                        PurchaseInvoiceItem.receipt_item_id.in_(valid_receipt_items),
                        PurchaseInvoice.doc_status != DocStatusEnum.CANCELLED,
                        PurchaseInvoice.id != pi.id,  # exclude self
                    )
                    .group_by(PurchaseInvoiceItem.receipt_item_id)
                ).all()
                billed_map = {rid: (qty or 0) for rid, qty in rows}

                for ln in lines_in:
                    rid = ln.get("receipt_item_id")
                    if rid:
                        if rid not in valid_receipt_items:
                            raise V.BizValidationError(
                                f"receipt_item_id {rid} does not belong to receipt {pi.receipt_id}.")
                        rec_it = rec_map[rid]
                        if Decimal(str(ln["rate"])) != Decimal(str(rec_it.unit_price or 0)):
                            raise V.BizValidationError(
                                "When billing against receipt, item rate must match the receipt item rate.")
                        already = Decimal(str(billed_map.get(rid, 0)))
                        available = Decimal(str(rec_it.accepted_qty)) - already
                        if Decimal(str(ln["quantity"])) > available:
                            raise V.BizValidationError(
                                f"Over-billing: {ln['quantity']} > available {available} for receipt item {rid}."
                            )

            # Upsert lines
            self.repo.sync_lines(pi, lines_in)

        # Recalc totals & outstanding (still draft)
        self.repo.recalc_total(pi)
        self.s.commit()
        return pi

    def _doc_type_id(self, code: str) -> int:
        dt = self.s.execute(select(DocumentType.id).where(DocumentType.code == code)).scalar_one_or_none()
        if not dt:
            raise V.BizValidationError(f"DocumentType '{code}' not found.")
        return dt

    def _guard_submittable(self, pi: PurchaseInvoice) -> None:
        V.guard_submittable_state(pi.doc_status)
        if pi.is_return and not pi.return_against_id:
            raise V.BizValidationError("Return Invoice must reference original invoice.")

    def submit_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        logger.info("🔄 PI submit start | invoice_id=%s", invoice_id)

        pi = self.repo.get_by_id(invoice_id, for_update=False)
        if not pi:
            logger.error("❌ PI submit aborted: not found | invoice_id=%s", invoice_id)
            raise NotFound("Purchase Invoice not found.")

        logger.info("📄 PI=%s | company=%s branch=%s | update_stock=%s is_return=%s",
                    pi.code, pi.company_id, pi.branch_id, pi.update_stock, pi.is_return)

        ensure_scope_by_ids(context=context, target_company_id=pi.company_id, target_branch_id=pi.branch_id)
        PostingDateValidator.validate_standalone_document(self.s, pi.posting_date, pi.company_id)
        self._guard_submittable(pi)

        # Build normalized line snapshots
        header_wh = pi.warehouse_id
        line_snaps = []
        for idx, it in enumerate(pi.items):
            line_snaps.append({
                "item_id": it.item_id,
                "uom_id": it.uom_id,
                "quantity": it.quantity,
                "rate": it.rate,
                "warehouse_id": it.warehouse_id,
                "doc_row_id": it.id,
            })
            logger.info("  PI line %s | item=%s qty=%s rate=%s wh=%s", idx + 1, it.item_id, it.quantity, it.rate,
                        it.warehouse_id)

        # Ensure warehouse for stock lines
        self._enforce_line_warehouses_if_stock(pi.update_stock, line_snaps, header_wh)

        # Load details and classify
        item_ids = [it.item_id for it in pi.items]
        details = self.repo.get_item_details_batch(pi.company_id, item_ids)
        stock_lines = []
        if pi.update_stock:
            for snap in line_snaps:
                item_detail = details.get(snap["item_id"], {})
                if item_detail.get("is_stock_item", False):
                    base = item_detail.get("base_uom_id")
                    stock_lines.append({**snap, "base_uom_id": base})
                    logger.info("  ✅ Stock item | item=%s base_uom=%s wh=%s", snap["item_id"], base,
                                snap["warehouse_id"])
                else:
                    logger.info("  ⏭️ Non-stock item | item=%s", snap["item_id"])

        doc_type_id = self._doc_type_id("PURCHASE_RETURN" if pi.is_return else "PURCHASE_INVOICE")
        posting_dt = resolve_posting_dt(pi.posting_date, created_at=pi.created_at, treat_midnight_as_date=True)
        logger.info("📅 PI posting_dt=%s", posting_dt)

        # STOCK PATH
        if pi.update_stock and stock_lines:
            logger.info("🚀 PI stock path | lines=%s", len(stock_lines))
            if pi.is_return:
                intents = build_intents_for_return(
                    company_id=pi.company_id, branch_id=pi.branch_id, warehouse_id=pi.warehouse_id,
                    posting_dt=posting_dt, doc_type_id=doc_type_id, doc_id=pi.id,
                    lines=[{
                        "uom_id": ln["uom_id"],
                        "item_id": ln["item_id"],
                        "accepted_qty": ln["quantity"],  # sign handled by builder
                        "unit_price": ln["rate"],
                        "doc_row_id": ln["doc_row_id"],
                        "base_uom_id": ln.get("base_uom_id"),
                        "warehouse_id": ln["warehouse_id"],
                    } for ln in stock_lines],
                    session=self.s
                )
            else:
                intents = build_intents_for_receipt(
                    company_id=pi.company_id, branch_id=pi.branch_id, warehouse_id=pi.warehouse_id,
                    posting_dt=posting_dt, doc_type_id=doc_type_id, doc_id=pi.id,
                    lines=[{
                        "uom_id": ln["uom_id"],
                        "item_id": ln["item_id"],
                        "accepted_qty": ln["quantity"],
                        "unit_price": ln["rate"],
                        "doc_row_id": ln["doc_row_id"],
                        "base_uom_id": ln.get("base_uom_id"),
                        "warehouse_id": ln["warehouse_id"],
                    } for ln in stock_lines],
                    session=self.s
                )

            for idx, it in enumerate(intents):
                if it.warehouse_id is None:
                    logger.error("❌ PI intent missing warehouse | idx=%s item_id=%s", idx, it.item_id)
                    raise V.BizValidationError(
                        "Internal error: PI intent without warehouse. Please check warehouses/UOMs.")

            pairs = {(i.item_id, i.warehouse_id) for i in intents}
            if not pairs:
                logger.error("❌ PI no SLE pairs generated while update_stock=True | invoice_id=%s", invoice_id)
                raise V.BizValidationError("No stock ledger pairs generated for stock items; check warehouses/UOMs.")

            # Backdated?
            def _future_exists(item_id: int, wh: int) -> bool:
                q = self.s.execute(
                    select(func.count()).select_from(StockLedgerEntry).where(
                        StockLedgerEntry.company_id == pi.company_id,
                        StockLedgerEntry.item_id == item_id,
                        StockLedgerEntry.warehouse_id == wh,
                        ((StockLedgerEntry.posting_date > posting_dt.date()) | and_(
                            StockLedgerEntry.posting_date == posting_dt.date(),
                            StockLedgerEntry.posting_time > posting_dt,
                        )),
                        StockLedgerEntry.is_cancelled == False,
                    )
                ).scalar() or 0
                return q > 0

            is_backdated = any(_future_exists(i, w) for (i, w) in pairs)
            if is_backdated:
                logger.warning("⚠️ PI is backdated; will replay inside TX | invoice_id=%s", invoice_id)

            # Single atomic block (like Sales)
            with self.s.begin_nested():
                pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
                self._guard_submittable(pi_locked)

                # Write SLEs
                with lock_pairs(self.s, pairs):
                    for idx, intent in enumerate(intents):
                        append_sle(self.s, intent, created_at_hint=pi_locked.created_at, tz_hint=None, batch_index=idx)

                # If backdated, replay now (KEYWORD ARGS!)
                if is_backdated:
                    for (item_id, wh_id) in pairs:
                        repost_from(
                            s=self.s,
                            company_id=pi_locked.company_id,
                            item_id=item_id,
                            warehouse_id=wh_id,
                            start_dt=posting_dt,
                            exclude_doc_types=set(),
                        )

                # Always derive bins after writes/replay
                for (item_id, wh_id) in pairs:
                    derive_bin(self.s, pi_locked.company_id, item_id, wh_id)

                # GL template selection
                has_receipt_items = any(x.receipt_item_id for x in pi_locked.items)
                template = "PURCHASE_RETURN_INVOICED" if pi_locked.is_return else (
                    "PURCHASE_INVOICE_DIRECT" if pi_locked.update_stock and not has_receipt_items else
                    "PURCHASE_INVOICE_AGAINST_RECEIPT"
                )

                total_amount = abs(Decimal(str(pi_locked.total_amount or 0)))
                stock_value = Decimal("0")
                service_value = Decimal("0")
                for it in pi_locked.items:
                    val = abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                    if details.get(it.item_id, {}).get("is_stock_item", False) and pi_locked.update_stock:
                        stock_value += val
                    else:
                        service_value += val

                payload = {
                    "invoice_lines": [{"quantity": it.quantity, "rate": it.rate, "item_id": it.item_id} for it in
                                      pi_locked.items],
                    "DOCUMENT_TOTAL": float(total_amount),
                    "update_stock": bool(pi_locked.update_stock),
                }
                if template == "PURCHASE_INVOICE_DIRECT":
                    payload["INVOICE_STOCK_VALUE"] = float(stock_value)
                    payload["INVOICE_SERVICE_VALUE"] = float(service_value)
                if template == "PURCHASE_RETURN_INVOICED":
                    payload["RETURN_STOCK_VALUE"] = float(stock_value)

                payable = pi_locked.payable_account_id
                if not payable:
                    from app.application_accounting.chart_of_accounts.models import Account
                    payable = self.s.execute(
                        select(Account.id).where(Account.company_id == pi_locked.company_id, Account.code == "2111")
                    ).scalar_one_or_none()
                    if not payable:
                        logger.error("❌ PI submit missing AP account 2111 | company=%s", pi_locked.company_id)
                        raise V.BizValidationError("Default Accounts Payable (2111) not found.")
                dyn_ctx = {"accounts_payable_account_id": payable}

                PostingService(self.s).post(
                    PostingContext(
                        company_id=pi_locked.company_id,
                        branch_id=pi_locked.branch_id,
                        source_doctype_id=doc_type_id,
                        source_doc_id=pi_locked.id,
                        posting_date=posting_dt,
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=None,
                        remarks=f"{'Purchase Return' if pi_locked.is_return else 'Purchase Invoice'} {pi_locked.code}",
                        template_code=template,
                        payload=payload,
                        runtime_accounts={},
                        party_id=pi_locked.supplier_id,
                        party_type=PartyTypeEnum.SUPPLIER,
                        dynamic_account_context=dyn_ctx,
                    )
                )

                pi_locked.doc_status = DocStatusEnum.RETURNED if pi_locked.is_return else DocStatusEnum.SUBMITTED
                self.repo.save(pi_locked)

            self.s.commit()
            logger.info("🎉 PI submit done (stock) | %s", pi.code)
            return pi

        # FINANCE-ONLY PATH (unchanged except formatting)
        logger.info("💳 PI finance-only path | invoice_id=%s", invoice_id)
        with self.s.begin_nested():
            pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
            self._guard_submittable(pi_locked)

            has_receipt_items = any(x.receipt_item_id for x in pi_locked.items)
            template = "PURCHASE_RETURN_INVOICED" if pi_locked.is_return else (
                "PURCHASE_INVOICE_AGAINST_RECEIPT" if (pi_locked.receipt_id or has_receipt_items) else
                "PURCHASE_INVOICE_DIRECT"
            )
            total_amount = abs(Decimal(str(pi_locked.total_amount or 0)))

            details2 = self.repo.get_item_details_batch(pi_locked.company_id, [x.item_id for x in pi_locked.items])
            stock_value = Decimal("0")
            service_value = Decimal("0")
            for it in pi_locked.items:
                val = abs(Decimal(str(it.quantity))) * Decimal(str(it.rate))
                if details2.get(it.item_id, {}).get("is_stock_item", False) and pi_locked.update_stock:
                    stock_value += val
                else:
                    service_value += val

            payload = {
                "invoice_lines": [{"quantity": it.quantity, "rate": it.rate, "item_id": it.item_id} for it in
                                  pi_locked.items],
                "DOCUMENT_TOTAL": float(total_amount),
                "update_stock": bool(pi_locked.update_stock),
            }
            if template == "PURCHASE_INVOICE_DIRECT":
                payload["INVOICE_STOCK_VALUE"] = float(stock_value)
                payload["INVOICE_SERVICE_VALUE"] = float(service_value)
            if template == "PURCHASE_RETURN_INVOICED":
                payload["RETURN_STOCK_VALUE"] = float(stock_value)

            payable = pi_locked.payable_account_id
            if not payable:
                from app.application_accounting.chart_of_accounts.models import Account
                payable = self.s.execute(
                    select(Account.id).where(Account.company_id == pi_locked.company_id, Account.code == "2111")
                ).scalar_one_or_none()
                if not payable:
                    logger.error("❌ PI submit missing AP account 2111 (finance-only) | company=%s",
                                 pi_locked.company_id)
                    raise V.BizValidationError("Default Accounts Payable (2111) not found.")
            dyn_ctx = {"accounts_payable_account_id": payable}

            PostingService(self.s).post(
                PostingContext(
                    company_id=pi_locked.company_id,
                    branch_id=pi_locked.branch_id,
                    source_doctype_id=doc_type_id,
                    source_doc_id=pi_locked.id,
                    posting_date=posting_dt,
                    created_by_id=context.user_id,
                    is_auto_generated=True,
                    entry_type=None,
                    remarks=f"{'Purchase Return' if pi_locked.is_return else 'Purchase Invoice'} {pi_locked.code}",
                    template_code=template,
                    payload=payload,
                    runtime_accounts={},
                    party_id=pi_locked.supplier_id,
                    party_type=PartyTypeEnum.SUPPLIER,
                )
            )

            pi_locked.doc_status = DocStatusEnum.RETURNED if pi_locked.is_return else DocStatusEnum.SUBMITTED
            self.repo.save(pi_locked)

        self.s.commit()
        logger.info("🎉 PI submit done (finance-only) | %s", pi.code)
        return pi

    def cancel_purchase_invoice(self, *, invoice_id: int, context: AffiliationContext) -> PurchaseInvoice:
        logger.info("♻️ PI cancel start | invoice_id=%s", invoice_id)

        # 1) Read & guards
        pi = self.repo.get_by_id(invoice_id, for_update=False)
        if not pi:
            raise NotFound("Purchase Invoice not found.")

        ensure_scope_by_ids(context=context, target_company_id=pi.company_id, target_branch_id=pi.branch_id)
        V.guard_cancellable_state(pi.doc_status)

        dt_id = self._doc_type_id("PURCHASE_RETURN" if pi.is_return else "PURCHASE_INVOICE")

        # Use your PostingDateValidator to normalize & enforce fiscal-period rules
        cancel_posting_dt = PostingDateValidator.validate_standalone_document(
            s=self.s,
            posting_date_or_dt=pi.posting_date,
            company_id=pi.company_id,
            created_at=pi.created_at,
            treat_midnight_as_date=True,
        )

        # 2) Collect SLEs to know what to cancel/replay
        rows = (
            self.s.execute(
                select(StockLedgerEntry)
                .where(
                    StockLedgerEntry.company_id == pi.company_id,
                    StockLedgerEntry.doc_type_id == dt_id,
                    StockLedgerEntry.doc_id == pi.id,
                    StockLedgerEntry.is_cancelled == False,
                    StockLedgerEntry.is_reversal == False,
                )
                .order_by(
                    StockLedgerEntry.posting_date.asc(),
                    StockLedgerEntry.posting_time.asc(),
                    StockLedgerEntry.id.asc(),
                )
            )
            .scalars()
            .all()
        )
        pairs = {(r.item_id, r.warehouse_id) for r in rows}
        start_dt = min((r.posting_time for r in rows), default=cancel_posting_dt)

        with self.s.begin_nested():
            # Lock and flip state
            pi_locked = self.repo.get_by_id(invoice_id, for_update=True)
            V.guard_cancellable_state(pi_locked.doc_status)
            pi_locked.doc_status = DocStatusEnum.CANCELLED
            self.repo.save(pi_locked)
            logger.info("📝 PI state -> CANCELLED | %s", pi_locked.code)

            # Cancel SLEs (under locks)
            if rows:
                with lock_pairs(self.s, pairs):
                    originals = (
                        self.s.execute(
                            select(StockLedgerEntry)
                            .where(
                                StockLedgerEntry.company_id == pi_locked.company_id,
                                StockLedgerEntry.doc_type_id == dt_id,
                                StockLedgerEntry.doc_id == pi_locked.id,
                                StockLedgerEntry.is_cancelled == False,
                                StockLedgerEntry.is_reversal == False,
                            )
                            .order_by(
                                StockLedgerEntry.posting_date.asc(),
                                StockLedgerEntry.posting_time.asc(),
                                StockLedgerEntry.id.asc(),
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for o in originals:
                        cancel_sle(self.s, o)

            # Replay bins/valuations
            if pairs:
                for (item_id, wh_id) in pairs:
                    repost_from(
                        s=self.s,
                        company_id=pi_locked.company_id,
                        item_id=item_id,
                        warehouse_id=wh_id,
                        start_dt=start_dt,
                        exclude_doc_types=set(),
                    )
                    logger.info("  🔄 Reposted from %s | item=%s wh=%s", start_dt, item_id, wh_id)

            # Reverse GL (PostingService.cancel ignores ctx.posting_date by design and uses original JE date)
            with self.s.no_autoflush:
                PostingService(self.s).cancel(
                    PostingContext(
                        company_id=pi_locked.company_id,
                        branch_id=pi_locked.branch_id,
                        source_doctype_id=dt_id,
                        source_doc_id=pi_locked.id,
                        posting_date=cancel_posting_dt,  # not used by cancel(); kept for parity/logs
                        created_by_id=context.user_id,
                        is_auto_generated=True,
                        entry_type=None,
                        remarks=f"Cancel {'Purchase Return' if pi_locked.is_return else 'Purchase Invoice'} {pi_locked.code}",
                        template_code=None,
                        payload={},  # nothing required for cancel path
                        runtime_accounts={},
                        party_id=pi_locked.supplier_id,
                        party_type=PartyTypeEnum.SUPPLIER,
                    )
                )
                logger.info("📘 GL cancel posted for %s", pi_locked.code)

        self.s.commit()
        logger.info("🎉 PI cancel done | %s", pi.code)
        return pi
