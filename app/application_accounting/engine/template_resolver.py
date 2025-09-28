# application_accounting/engine/template_resolver.py
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from app.application_accounting.chart_of_accounts.models import GLEntryTemplate
from app.application_accounting.engine.errors import TemplateNotFoundError
from app.application_accounting.engine.selectors import get_template_by_code, get_primary_template


def pick_template(
    s: Session,
    *, company_id: int, source_doctype_id: int,
    explicit_code: Optional[str] = None
) -> GLEntryTemplate:
    if explicit_code:
        t = get_template_by_code(s, company_id, source_doctype_id, explicit_code)
        if not t:
            raise TemplateNotFoundError(f"GL template {explicit_code} not found for company {company_id}.")
        return t
    t = get_primary_template(s, company_id, source_doctype_id)
    if not t:
        raise TemplateNotFoundError(f"No primary GL template configured for doctype {source_doctype_id}.")
    return t
