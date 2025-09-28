# application_accounting/handlers/depreciation.py
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session

from app.application_accounting.engine.posting_service import PostingContext, PostingService


def post_depreciation(
    s: Session, *, company_id: int, branch_id: int, posting_date: datetime,
    created_by_id: int, source_doctype_id: int, source_doc_id: int,
    depreciation_amount: float
) -> None:
    ctx = PostingContext(
        company_id=company_id, branch_id=branch_id,
        source_doctype_id=source_doctype_id, source_doc_id=source_doc_id,
        posting_date=posting_date, created_by_id=created_by_id,
        is_auto_generated=True, remarks=f"Depreciation {source_doc_id}",
        template_code="DEPRECIATION_STANDARD",
        payload={"DEPRECIATION_AMOUNT": depreciation_amount},
        runtime_accounts={},
    )
    PostingService(s).post(ctx)
