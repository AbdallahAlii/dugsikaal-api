# app/application_print/query_builders/list_query.py
from __future__ import annotations

from sqlalchemy.sql import Select, select
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_print.models import PrintFormat


def build_print_format_list_query(
    session: Session,
    ctx: AffiliationContext,
) -> Select:
    """
    Example: list print formats for current company (or global).
    You can use this later to expose a UI for managing print formats.
    """
    q = select(PrintFormat)

    company_id = getattr(ctx, "company_id", None)
    if company_id is not None:
        q = q.where(
            (PrintFormat.company_id == company_id) |
            (PrintFormat.company_id.is_(None))
        )

    return q
