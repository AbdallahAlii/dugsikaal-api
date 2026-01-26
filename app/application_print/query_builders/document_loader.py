# app/application_print/query_builders/document_loader.py
from __future__ import annotations

from typing import Any, Dict
from sqlalchemy.orm import Session

from app.security.rbac_effective import AffiliationContext
from app.application_doctypes.core_lists.config import get_detail_config


def load_document_via_detail_config(
    *,
    module: str,
    entity: str,
    session: Session,
    ctx: AffiliationContext,
    doc_id: int,
) -> Dict[str, Any] | None:
    """
    Convenience helper to use DetailConfig loader directly.
    Not required for the core printing flow, but available if needed.
    """
    detail_cfg = get_detail_config(module, entity)
    return detail_cfg.loader(session, ctx, doc_id)
