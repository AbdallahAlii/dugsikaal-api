# # app/application_print/services/format_resolver.py

from __future__ import annotations

import logging
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.application_print.models import PrintFormat

log = logging.getLogger(__name__)

def resolve_print_format(session: Session, *, doctype: str, company_id: Optional[int], format_code: Optional[str]) -> Optional[PrintFormat]:
    """
    Resolve the best PrintFormat, roughly matching ERPNext behaviour:
    Priority (if format_code given):
      1) company-specific with that code
      2) global with that code
    Otherwise:
      1) company-specific default
      2) global default
      3) company-specific standard
      4) global standard
      5) any (company or global) as last resort
    """
    try:
        log.info(f"Resolving print format for {doctype} with company_id {company_id} and format_code {format_code}")
        q = session.query(PrintFormat).filter(PrintFormat.doctype == doctype)

        if company_id is not None:
            q = q.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
        else:
            q = q.filter(PrintFormat.company_id.is_(None))

        if format_code:
            pf = q.filter(PrintFormat.code == format_code).order_by(PrintFormat.company_id.is_(None).asc()).first()
            if pf:
                log.info(f"Found print format by code: {pf.code}")
                return pf

        pf = q.filter(PrintFormat.company_id.is_(None), PrintFormat.is_default_for_doctype.is_(True)).first()
        if pf:
            log.info(f"Found global default print format: {pf.code}")
            return pf

        pf = q.filter(PrintFormat.company_id == company_id, PrintFormat.is_default_for_doctype.is_(True)).first()
        if pf:
            log.info(f"Found company-specific default print format: {pf.code}")
            return pf

        pf = q.filter(PrintFormat.company_id.is_(None), PrintFormat.is_standard.is_(True)).first()
        if pf:
            log.info(f"Found global standard print format: {pf.code}")
            return pf

        pf = q.first()
        log.info(f"Using first available print format: {pf.code if pf else 'None'}")
        return pf
    except Exception as e:
        log.error(f"Error resolving print format for {doctype} with company_id {company_id}: {e}")
        raise
