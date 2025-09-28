# seed_data/doctypes/seeder.py
from __future__ import annotations
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.models.base import StatusEnum
# ⬇️ adjust this import to your actual model location
from app.application_stock.stock_models import DocumentType, DocumentDomain  # <- fix path if needed
from .data import DOCTYPE_TYPES

logger = logging.getLogger(__name__)


def _get_or_create_by_code(
    db: Session,
    *,
    code: str,
    defaults: Optional[dict] = None
) -> Tuple[DocumentType, bool]:
    obj = db.scalar(select(DocumentType).where(DocumentType.code == code))
    if obj:
        return obj, False

    obj = DocumentType(code=code, **(defaults or {}))
    db.add(obj)
    try:
        db.flush()
        return obj, True
    except IntegrityError:
        db.rollback()
        obj = db.scalar(select(DocumentType).where(DocumentType.code == code))
        return obj, False


def _domain_from_str(s: str) -> DocumentDomain:
    s = (s or "").strip().upper()
    if s == "INVENTORY":
        return DocumentDomain.INVENTORY
    if s == "FINANCE":
        return DocumentDomain.FINANCE
    if s == "ASSETS":
        return DocumentDomain.ASSETS
    if s == "PAYROLL":
        return DocumentDomain.PAYROLL
    return DocumentDomain.OTHER


def seed_document_types(db: Session) -> None:
    """
    Idempotent seeding of DocumentType registry.
    - Creates by code if missing
    - Updates label/domain/affects_* if changed
    """
    logger.info("Seeding document types...")

    for spec in DOCTYPE_TYPES:
        code          = spec["code"].strip().upper()
        label         = spec["label"].strip()
        domain        = _domain_from_str(spec["domain"])
        affects_stock = bool(spec["affects_stock"])
        affects_gl    = bool(spec["affects_gl"])

        defaults = dict(
            label=label,
            domain=domain,
            affects_stock=affects_stock,
            affects_gl=affects_gl,
            status=StatusEnum.ACTIVE,
        )

        row, created = _get_or_create_by_code(db, code=code, defaults=defaults)
        if created:
            logger.info("  + %s (%s) created", label, code)
        else:
            changed = False
            if row.label != label:
                row.label = label; changed = True
            if row.domain != domain:
                row.domain = domain; changed = True
            if row.affects_stock != affects_stock:
                row.affects_stock = affects_stock; changed = True
            if row.affects_gl != affects_gl:
                row.affects_gl = affects_gl; changed = True
            if row.status != StatusEnum.ACTIVE:
                row.status = StatusEnum.ACTIVE; changed = True
            if changed:
                logger.info("  ~ %s (%s) updated", label, code)

    db.commit()
    logger.info("✅ Document types seeding complete.")
