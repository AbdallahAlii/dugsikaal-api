# application_accounting/selectors.py
from __future__ import annotations
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from typing import Optional, List

from app.application_accounting.chart_of_accounts.models import Account, GLEntryTemplate, GLTemplateItem


def get_account_by_code(s: Session, company_id: int, code: str) -> Optional[Account]:
    return s.execute(
        select(Account).where(Account.company_id == company_id, Account.code == code)
    ).scalar_one_or_none()

def get_account_id_by_code(s: Session, company_id: int, code: str) -> Optional[int]:
    acc = get_account_by_code(s, company_id, code)
    return acc.id if acc else None

def get_template_by_code(s: Session, company_id: int, source_doctype_id: int, code: str) -> Optional[GLEntryTemplate]:
    return s.execute(
        select(GLEntryTemplate).where(
            GLEntryTemplate.company_id == company_id,
            GLEntryTemplate.source_doctype_id == source_doctype_id,
            GLEntryTemplate.code == code,
            GLEntryTemplate.is_active == True,  # noqa
        )
    ).scalar_one_or_none()

def get_primary_template(s: Session, company_id: int, source_doctype_id: int) -> Optional[GLEntryTemplate]:
    return s.execute(
        select(GLEntryTemplate).where(
            GLEntryTemplate.company_id == company_id,
            GLEntryTemplate.source_doctype_id == source_doctype_id,
            GLEntryTemplate.is_active == True,  # noqa
            GLEntryTemplate.is_primary == True, # noqa
        )
    ).scalar_one_or_none()

def get_template_items(s: Session, template_id: int) -> List[GLTemplateItem]:
    return list(s.execute(
        select(GLTemplateItem).where(GLTemplateItem.template_id == template_id).order_by(GLTemplateItem.sequence.asc())
    ).scalars().all())
