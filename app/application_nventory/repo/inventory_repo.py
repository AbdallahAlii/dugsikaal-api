from __future__ import annotations
from typing import Optional, Dict, Any
import logging

from sqlalchemy import select, func, or_, delete
from sqlalchemy.orm import Session

from app.application_nventory.inventory_models import Brand, UnitOfMeasure, Item, UOMConversion, ItemGroup
from config.database import db

log = logging.getLogger(__name__)
# Map internal doc codes -> user-friendly label

DOC_LABELS: dict[str, str] = {
    "PURCHASE_RECEIPT": "Purchase Receipt",
    "PURCHASE_INVOICE": "Purchase Invoice",
    "SALES_INVOICE": "Sales Invoice",
    "SALES_DELIVERY_NOTE": "Sales Delivery Note",
    "SALES_QUOTATION": "Sales Quotation",
    "STOCK_ENTRY": "Stock Entry",
    "STOCK_RECONCILIATION": "Stock Reconciliation",
}

class InventoryRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # --- Brand CRUD ---
    def get_brand_by_id(self, brand_id: int) -> Optional[Brand]:
        return self.s.get(Brand, brand_id)

    def get_brand_by_name(self, company_id: int, name: str) -> Optional[Brand]:
        return self.s.scalar(
            select(Brand).where(
                Brand.company_id == company_id,
                func.lower(Brand.name) == func.lower(name),
            )
        )

    def create_brand(self, brand: Brand) -> Brand:
        self.s.add(brand)
        self.s.flush([brand])
        return brand

    def update_brand(self, brand: Brand, updates: dict) -> None:
        for key, value in updates.items():
            setattr(brand, key, value)
        self.s.flush([brand])

    # NOTE: keep if used elsewhere
    def delete_brand(self, brand_id: int) -> int:
        return self.s.query(Brand).filter(Brand.id == brand_id).delete(synchronize_session="fetch")

    # --- UnitOfMeasure CRUD ---
    def get_uom_by_id(self, uom_id: int) -> Optional[UnitOfMeasure]:
        return self.s.get(UnitOfMeasure, uom_id)

    def get_uom_by_name(self, company_id: int, name: str) -> Optional[UnitOfMeasure]:
        return self.s.scalar(
            select(UnitOfMeasure).where(
                UnitOfMeasure.company_id == company_id,
                func.lower(UnitOfMeasure.name) == func.lower(name),
            )
        )

    def create_uom(self, uom: UnitOfMeasure) -> UnitOfMeasure:
        self.s.add(uom)
        self.s.flush([uom])
        return uom


    # --- Item CRUD ---
    def get_item_by_id(self, item_id: int) -> Optional[Item]:
        return self.s.get(Item, item_id)

    def get_item_by_name(self, company_id: int, name: str) -> Optional[Item]:
        return self.s.scalar(
            select(Item).where(
                Item.company_id == company_id,
                func.lower(Item.name) == func.lower(name),
            )
        )

    def get_item_by_sku(self, company_id: int, sku: str) -> Optional[Item]:
        return self.s.scalar(
            select(Item).where(
                Item.company_id == company_id,
                func.lower(Item.sku) == func.lower(sku),
            )
        )

    def create_item(self, item: Item) -> Item:
        self.s.add(item)
        self.s.flush([item])
        return item

    def update_item(self, item: Item, updates: dict) -> None:
        for key, value in updates.items():
            setattr(item, key, value)
        self.s.flush([item])

    # NOTE: keep if used elsewhere
    def delete_item(self, item_id: int) -> int:
        return self.s.query(Item).filter(Item.id == item_id).delete(synchronize_session="fetch")

    # --- UOMConversion helpers ---
    def flush_model(self, model):
        self.s.flush([model])

    def get_uom_conversion(self, item_id: int, uom_id: int) -> Optional[UOMConversion]:
        return self.s.scalar(
            select(UOMConversion).where(
                UOMConversion.item_id == item_id,
                getattr(UOMConversion, "uom_id") == uom_id,  # safe if column exists
            )
        )

    def get_item_by_name_excluding_id(self, company_id: int, name: str, exclude_item_id: int) -> Optional[Item]:
        return self.s.scalar(
            select(Item).where(
                Item.company_id == company_id,
                func.lower(Item.name) == func.lower(name),
                Item.id != exclude_item_id,
            )
        )

    # -------------------------------------------------------------------------
    # Linked Document Guards (ERPNext-style)
    # Returns {"doctype": "...", "code": "..."} or None
    # -------------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _label(self, raw: str) -> str:
        return DOC_LABELS.get(raw, raw.replace("_", " ").title())

    def _first_scalar(self, stmt):
        return self.s.execute(stmt).scalar_one_or_none()

    def _sle_fallback(
            self,
            *,
            company_id: int,
            item_id: Optional[int] = None,
            uom_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Last-resort fallback using StockLedgerEntry -> DocumentType.
        Returns {"doctype": "<label>", "code": "<doc_code>"}.
        """
        try:
            from app.application_stock.stock_models import StockLedgerEntry, DocumentType  # type: ignore
        except Exception:
            return None

        preds = [StockLedgerEntry.company_id == company_id]
        if item_id is not None:
            preds.append(StockLedgerEntry.item_id == item_id)
        if uom_id is not None:
            preds.append(or_(StockLedgerEntry.base_uom_id == uom_id, StockLedgerEntry.transaction_uom_id == uom_id))

        row = self.s.execute(
            select(DocumentType.code, DocumentType.label, StockLedgerEntry.doc_id)
            .join(DocumentType, DocumentType.id == StockLedgerEntry.doc_type_id)
            .where(*preds)
            .limit(1)
        ).first()

        if not row:
            return None

        dt_code, dt_label, doc_id = row
        dt_code = str(dt_code)
        label = str(dt_label) if dt_label else self._label(dt_code)

        resolved_code = None
        try:
            if dt_code == "PURCHASE_RECEIPT":
                from app.application_buying.models import PurchaseReceipt  # type: ignore
                resolved_code = self._first_scalar(
                    select(PurchaseReceipt.code).where(PurchaseReceipt.id == doc_id).limit(1))

            elif dt_code == "PURCHASE_INVOICE":
                from app.application_buying.models import PurchaseInvoice  # type: ignore
                resolved_code = self._first_scalar(
                    select(PurchaseInvoice.code).where(PurchaseInvoice.id == doc_id).limit(1))

            elif dt_code == "SALES_INVOICE":
                from app.application_selling.models import SalesInvoice  # type: ignore
                resolved_code = self._first_scalar(select(SalesInvoice.code).where(SalesInvoice.id == doc_id).limit(1))

            elif dt_code == "SALES_DELIVERY_NOTE":
                from app.application_selling.models import SalesDeliveryNote  # type: ignore
                resolved_code = self._first_scalar(
                    select(SalesDeliveryNote.code).where(SalesDeliveryNote.id == doc_id).limit(1))

            elif dt_code == "SALES_QUOTATION":
                from app.application_selling.models import SalesQuotation  # type: ignore
                resolved_code = self._first_scalar(
                    select(SalesQuotation.code).where(SalesQuotation.id == doc_id).limit(1))

            elif dt_code == "STOCK_ENTRY":
                from app.application_stock.stock_models import StockEntry  # type: ignore
                resolved_code = self._first_scalar(select(StockEntry.code).where(StockEntry.id == doc_id).limit(1))

            elif dt_code == "STOCK_RECONCILIATION":
                from app.application_stock.stock_models import StockReconciliation  # type: ignore
                resolved_code = self._first_scalar(
                    select(StockReconciliation.code).where(StockReconciliation.id == doc_id).limit(1))
        except Exception:
            resolved_code = None

        code_out = str(resolved_code) if resolved_code else str(doc_id)
        return {"doctype": label, "code": code_out}

        # ------------------------------------------------------------------
        # Linked Document Guards (ERPNext style)
        # Return {"doctype": "...", "code": "..."} OR None
        # ------------------------------------------------------------------

    def find_first_linked_document_brand(self, company_id: int, brand_id: int) -> Optional[Dict[str, Any]]:
        sku = self._first_scalar(
            select(Item.sku).where(Item.company_id == company_id, Item.brand_id == brand_id).limit(1)
        )
        if sku:
            return {"doctype": "Item", "code": str(sku)}
        return None

    def find_first_linked_document_uom(self, company_id: int, uom_id: int) -> Optional[Dict[str, Any]]:
        sku = self._first_scalar(
            select(Item.sku).where(Item.company_id == company_id, Item.base_uom_id == uom_id).limit(1)
        )
        if sku:
            return {"doctype": "Item", "code": str(sku)}

        conv_id = self._first_scalar(
            select(UOMConversion.id)
            .join(Item, Item.id == UOMConversion.item_id)
            .where(
                Item.company_id == company_id,
                or_(
                    UOMConversion.uom_id == uom_id,
                    getattr(UOMConversion, "to_uom_id", None) == uom_id,
                ),
            )
            .limit(1)
        )
        if conv_id:
            return {"doctype": "UOM Conversion", "code": str(conv_id)}

        try:
            from app.application_nventory.inventory_models import ItemPrice  # type: ignore
            ip_code = self._first_scalar(
                select(ItemPrice.code).where(ItemPrice.company_id == company_id, ItemPrice.uom_id == uom_id).limit(1))
            if ip_code:
                return {"doctype": "Item Price", "code": str(ip_code)}
        except Exception:
            pass

        try:
            from app.application_stock.stock_models import StockEntryItem, StockEntry  # type: ignore
            se_code = self._first_scalar(
                select(StockEntry.code)
                .join(StockEntry, StockEntry.id == StockEntryItem.stock_entry_id)
                .where(StockEntry.company_id == company_id, StockEntryItem.uom_id == uom_id)
                .limit(1)
            )
            if se_code:
                return {"doctype": "Stock Entry", "code": str(se_code)}
        except Exception:
            pass

        try:
            from app.application_buying.models import PurchaseReceiptItem, PurchaseReceipt  # type: ignore
            pr_code = self._first_scalar(
                select(PurchaseReceipt.code)
                .join(PurchaseReceipt, PurchaseReceipt.id == PurchaseReceiptItem.receipt_id)
                .where(PurchaseReceipt.company_id == company_id, PurchaseReceiptItem.uom_id == uom_id)
                .limit(1)
            )
            if pr_code:
                return {"doctype": "Purchase Receipt", "code": str(pr_code)}
        except Exception:
            pass

        try:
            from app.application_buying.models import PurchaseInvoiceItem, PurchaseInvoice  # type: ignore
            pin_code = self._first_scalar(
                select(PurchaseInvoice.code)
                .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id)
                .where(PurchaseInvoice.company_id == company_id, PurchaseInvoiceItem.uom_id == uom_id)
                .limit(1)
            )
            if pin_code:
                return {"doctype": "Purchase Invoice", "code": str(pin_code)}
        except Exception:
            pass

        try:
            from app.application_selling.models import (  # type: ignore
                SalesQuotationItem, SalesQuotation,
                SalesDeliveryNoteItem, SalesDeliveryNote,
                SalesInvoiceItem, SalesInvoice,
            )

            sq_code = self._first_scalar(
                select(SalesQuotation.code)
                .join(SalesQuotation, SalesQuotation.id == SalesQuotationItem.quotation_id)
                .where(SalesQuotation.company_id == company_id, SalesQuotationItem.uom_id == uom_id)
                .limit(1)
            )
            if sq_code:
                return {"doctype": "Sales Quotation", "code": str(sq_code)}

            dn_code = self._first_scalar(
                select(SalesDeliveryNote.code)
                .join(SalesDeliveryNote, SalesDeliveryNote.id == SalesDeliveryNoteItem.delivery_note_id)
                .where(SalesDeliveryNote.company_id == company_id, SalesDeliveryNoteItem.uom_id == uom_id)
                .limit(1)
            )
            if dn_code:
                return {"doctype": "Sales Delivery Note", "code": str(dn_code)}

            si_code = self._first_scalar(
                select(SalesInvoice.code)
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceItem.invoice_id)
                .where(SalesInvoice.company_id == company_id, SalesInvoiceItem.uom_id == uom_id)
                .limit(1)
            )
            if si_code:
                return {"doctype": "Sales Invoice", "code": str(si_code)}
        except Exception:
            pass

        return self._sle_fallback(company_id=company_id, uom_id=uom_id)

    def find_first_linked_document_item(self, company_id: int, item_id: int) -> Optional[Dict[str, Any]]:
        try:
            from app.application_stock.stock_models import StockEntryItem, StockEntry  # type: ignore
            se_code = self._first_scalar(
                select(StockEntry.code)
                .join(StockEntry, StockEntry.id == StockEntryItem.stock_entry_id)
                .where(StockEntry.company_id == company_id, StockEntryItem.item_id == item_id)
                .limit(1)
            )
            if se_code:
                return {"doctype": "Stock Entry", "code": str(se_code)}
        except Exception:
            pass

        # ✅ FIX: Stock exists should be clean ERPNext-style (not "Bin Stock exists")
        try:
            from app.application_stock.stock_models import Bin  # type: ignore
            has_bin = self._first_scalar(
                select(Bin.id).where(Bin.company_id == company_id, Bin.item_id == item_id).limit(1))
            if has_bin:
                return {"doctype": "Stock", "code": "exists"}
        except Exception:
            pass

        try:
            from app.application_buying.models import PurchaseReceiptItem, PurchaseReceipt  # type: ignore
            pr_code = self._first_scalar(
                select(PurchaseReceipt.code)
                .join(PurchaseReceipt, PurchaseReceipt.id == PurchaseReceiptItem.receipt_id)
                .where(PurchaseReceipt.company_id == company_id, PurchaseReceiptItem.item_id == item_id)
                .limit(1)
            )
            if pr_code:
                return {"doctype": "Purchase Receipt", "code": str(pr_code)}
        except Exception:
            pass

        try:
            from app.application_buying.models import PurchaseInvoiceItem, PurchaseInvoice  # type: ignore
            pin_code = self._first_scalar(
                select(PurchaseInvoice.code)
                .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceItem.invoice_id)
                .where(PurchaseInvoice.company_id == company_id, PurchaseInvoiceItem.item_id == item_id)
                .limit(1)
            )
            if pin_code:
                return {"doctype": "Purchase Invoice", "code": str(pin_code)}
        except Exception:
            pass

        try:
            from app.application_selling.models import (  # type: ignore
                SalesQuotationItem, SalesQuotation,
                SalesDeliveryNoteItem, SalesDeliveryNote,
                SalesInvoiceItem, SalesInvoice,
            )

            sq_code = self._first_scalar(
                select(SalesQuotation.code)
                .join(SalesQuotation, SalesQuotation.id == SalesQuotationItem.quotation_id)
                .where(SalesQuotation.company_id == company_id, SalesQuotationItem.item_id == item_id)
                .limit(1)
            )
            if sq_code:
                return {"doctype": "Sales Quotation", "code": str(sq_code)}

            dn_code = self._first_scalar(
                select(SalesDeliveryNote.code)
                .join(SalesDeliveryNote, SalesDeliveryNote.id == SalesDeliveryNoteItem.delivery_note_id)
                .where(SalesDeliveryNote.company_id == company_id, SalesDeliveryNoteItem.item_id == item_id)
                .limit(1)
            )
            if dn_code:
                return {"doctype": "Sales Delivery Note", "code": str(dn_code)}

            si_code = self._first_scalar(
                select(SalesInvoice.code)
                .join(SalesInvoice, SalesInvoice.id == SalesInvoiceItem.invoice_id)
                .where(SalesInvoice.company_id == company_id, SalesInvoiceItem.item_id == item_id)
                .limit(1)
            )
            if si_code:
                return {"doctype": "Sales Invoice", "code": str(si_code)}
        except Exception:
            pass

        try:
            from app.application_nventory.inventory_models import ItemPrice  # type: ignore
            ip_code = self._first_scalar(
                select(ItemPrice.code).where(ItemPrice.company_id == company_id, ItemPrice.item_id == item_id).limit(1))
            if ip_code:
                return {"doctype": "Item Price", "code": str(ip_code)}
        except Exception:
            pass

        return self._sle_fallback(company_id=company_id, item_id=item_id)

    # -----------------------
    # Delete + link check (fast)
    # -----------------------
    def delete_item_group(self, *, company_id: int, item_group_id: int) -> int:
        res = self.s.execute(
            delete(ItemGroup).where(ItemGroup.company_id == int(company_id), ItemGroup.id == int(item_group_id))
        )
        return int(res.rowcount or 0)

    def find_first_linked_document_item_group(self, company_id: int, group_id: int) -> Optional[Dict[str, Any]]:
        """
        Optimized linked document check for item groups.
        Compatible with service call pattern.
        """
        # 1) Child item groups (single query)
        child_code = self.s.scalar(
            select(ItemGroup.code).where(
                ItemGroup.company_id == int(company_id),
                ItemGroup.parent_item_group_id == int(group_id),
            ).limit(1)
        )
        if child_code:
            return {"doctype": "Item Group", "code": str(child_code)}

        # 2) Items under group (single query)
        sku = self.s.scalar(
            select(Item.sku).where(
                Item.company_id == int(company_id),
                Item.item_group_id == int(group_id),
            ).limit(1)
        )
        if sku:
            return {"doctype": "Item", "code": str(sku)}

        return None
