# seed_data/gl_templates/seeder.py
from __future__ import annotations
import logging
from typing import Dict, Optional, List

from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session

# Models (adjust import paths to your project layout)
from app.application_accounting.chart_of_accounts.models import (
    Account,
    GLEntryTemplate,
    GLTemplateItem,
    DebitOrCreditEnum,
)
# If your DocumentType model lives elsewhere, update this import accordingly:
from ...application_stock.stock_models import DocumentType  # keep as in your codebase

from .data import TEMPLATE_DEFS, TEMPLATE_ITEMS

logger = logging.getLogger(__name__)


def _doctype_id(db: Session, code: str) -> Optional[int]:
    dt = db.scalar(select(DocumentType).where(DocumentType.code == code))
    return int(dt.id) if dt else None


def _acct_index(db: Session, company_id: int) -> Dict[str, Account]:
    rows = db.scalars(select(Account).where(Account.company_id == company_id)).all()
    return {a.code: a for a in rows}


def _ensure_single_primary(db: Session, *, company_id: int, doctype_id: int, keep_template_id: int) -> None:
    """
    Enforce a single primary template per (company, doctype).
    """
    db.execute(
        update(GLEntryTemplate)
        .where(
            GLEntryTemplate.company_id == company_id,
            GLEntryTemplate.source_doctype_id == doctype_id,
            GLEntryTemplate.id != keep_template_id,
            GLEntryTemplate.is_primary.is_(True),
        )
        .values(is_primary=False)
    )


def _get_or_create_template(
    db: Session,
    *,
    company_id: int,
    source_doctype_id: int,
    code: str,
    label: str,
    description: Optional[str],
    is_active: bool,
    is_primary: bool,
) -> GLEntryTemplate:
    tpl = db.scalar(
        select(GLEntryTemplate).where(
            GLEntryTemplate.company_id == company_id,
            GLEntryTemplate.source_doctype_id == source_doctype_id,
            GLEntryTemplate.code == code,
        )
    )
    if tpl:
        tpl.label = label
        tpl.description = description
        tpl.is_active = is_active
        tpl.is_primary = is_primary
        db.flush([tpl])
        if is_primary:
            _ensure_single_primary(db, company_id=company_id, doctype_id=source_doctype_id, keep_template_id=tpl.id)
        return tpl

    tpl = GLEntryTemplate(
        company_id=company_id,
        source_doctype_id=source_doctype_id,
        code=code,
        label=label,
        description=description,
        is_active=is_active,
        is_primary=is_primary,
    )
    db.add(tpl)
    db.flush([tpl])

    if is_primary:
        _ensure_single_primary(db, company_id=company_id, doctype_id=source_doctype_id, keep_template_id=tpl.id)

    return tpl


def _reset_items_for_template(
    db: Session,
    template_id: int,
    items: List[dict],
    acct_idx: Dict[str, Account],
) -> None:
    """
    Replace all items for a template (authoritative seed).
    """
    db.execute(delete(GLTemplateItem).where(GLTemplateItem.template_id == template_id))

    for row in items:
        requires_dynamic = bool(row.get("requires_dynamic_account", False))
        acct_id: Optional[int] = None

        acct_code = row.get("account_code")
        if not requires_dynamic:
            if not acct_code:
                logger.error("Template %s item missing static account_code and not dynamic; skipping.", template_id)
                continue
            acct = acct_idx.get(acct_code)
            if not acct:
                logger.error("Template %s item refers to unknown account_code %r; skipping.", template_id, acct_code)
                continue
            acct_id = int(acct.id)

        eff_str = (row.get("effect") or "").upper()
        try:
            effect_enum = DebitOrCreditEnum[eff_str]  # "DEBIT" | "CREDIT"
        except KeyError:
            logger.error("Template %s item has invalid effect %r; skipping.", template_id, eff_str)
            continue

        amt_src = row.get("amount_source")
        if not amt_src:
            logger.error("Template %s item missing amount_source; skipping.", template_id)
            continue

        db.add(
            GLTemplateItem(
                template_id=template_id,
                account_id=acct_id,  # None for dynamic rows
                sequence=int(row.get("sequence", 0)),
                effect=effect_enum,
                amount_source=amt_src,
                is_required=bool(row.get("is_required", True)),
                requires_dynamic_account=requires_dynamic,
                context_key=row.get("context_key"),
            )
        )
    db.flush()


def seed_gl_templates(db: Session, company_id: int) -> None:
    """
    Idempotent GL template seed for a company:
      - Ensures DocTypes exist (by code) and resolves IDs
      - Upserts GLEntryTemplate headers (enforcing one primary per (company,doctype))
      - Replaces GLTemplateItem rows per template
    """
    logger.info("📘 Seeding GL Entry Templates for company_id=%s", company_id)

    acct_idx = _acct_index(db, company_id)

    # 1) Upsert template headers and cache ids by template_code
    code_to_tpl_id: Dict[str, int] = {}
    for hdr in TEMPLATE_DEFS:
        dt_code = hdr["doctype_code"]
        dt_id = _doctype_id(db, dt_code)
        if not dt_id:
            logger.error("DocumentType %r not found; skipping template code=%r", dt_code, hdr.get("code"))
            continue

        tpl = _get_or_create_template(
            db,
            company_id=company_id,
            source_doctype_id=dt_id,
            code=hdr["code"],
            label=hdr["label"],
            description=hdr.get("description"),
            is_active=bool(hdr.get("is_active", True)),
            is_primary=bool(hdr.get("is_primary", False)),
        )
        code_to_tpl_id[hdr["code"]] = int(tpl.id)

    # 2) Group items by template_code and replace lines
    items_by_code: Dict[str, List[dict]] = {}
    for it in TEMPLATE_ITEMS:
        items_by_code.setdefault(it["template_code"], []).append(it)

    for tcode, tid in code_to_tpl_id.items():
        rows = items_by_code.get(tcode, [])
        _reset_items_for_template(db, tid, rows, acct_idx)

    db.commit()
    logger.info("✅ GL templates seeded for company_id=%s", company_id)
