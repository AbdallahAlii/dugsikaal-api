# # app/application_print/repository/print_repo.py

from __future__ import annotations

from typing import Optional, Dict, Any

from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from config.database import db
from app.application_print.models import (
    PrintLetterhead,
    PrintStyle,
    PrintSettings,
    PrintFormat,
    PrintFormatFieldTemplate,
)


class PrintRepository:
    def __init__(self, session: Optional[Session] = None):
        self.s: Session = session or db.session

    # -----------------------------
    # Styles
    # -----------------------------

    def get_style_by_id(self, style_id: int) -> Optional[PrintStyle]:
        return self.s.get(PrintStyle, style_id)

    def get_style_by_code(self, code: str, company_id: Optional[int]) -> Optional[PrintStyle]:
        q = self.s.query(PrintStyle).filter(PrintStyle.code == code, PrintStyle.is_disabled.is_(False))
        if company_id is not None:
            q = q.filter(or_(PrintStyle.company_id == company_id, PrintStyle.company_id.is_(None)))
        else:
            q = q.filter(PrintStyle.company_id.is_(None))
        # prefer company-specific first
        return q.order_by(PrintStyle.company_id.is_(None).asc()).first()

    def create_style(self, style: PrintStyle) -> PrintStyle:
        self.s.add(style)
        self.s.flush([style])
        return style

    def update_style_fields(self, style: PrintStyle, data: Dict[str, Any]) -> None:
        for field, value in data.items():
            if hasattr(style, field) and value is not None:
                setattr(style, field, value)
        self.s.flush([style])

    def clear_default_global_style(self, exclude_id: Optional[int] = None) -> None:
        q = self.s.query(PrintStyle).filter(PrintStyle.is_default_global.is_(True))
        if exclude_id:
            q = q.filter(PrintStyle.id != exclude_id)
        q.update({PrintStyle.is_default_global: False})
        self.s.flush()

    # -----------------------------
    # Letterheads
    # -----------------------------

    def get_letterhead_by_id(self, letterhead_id: int) -> Optional[PrintLetterhead]:
        return self.s.get(PrintLetterhead, letterhead_id)

    def get_default_letterhead_for_company(self, company_id: int) -> Optional[PrintLetterhead]:
        return (
            self.s.query(PrintLetterhead)
            .filter(
                PrintLetterhead.company_id == company_id,
                PrintLetterhead.is_disabled.is_(False),
                PrintLetterhead.is_default_for_company.is_(True),
            )
            .first()
        )

    def list_letterheads_for_company(self, company_id: int) -> list[PrintLetterhead]:
        return (
            self.s.query(PrintLetterhead)
            .filter(PrintLetterhead.company_id == company_id, PrintLetterhead.is_disabled.is_(False))
            .order_by(PrintLetterhead.is_default_for_company.desc(), PrintLetterhead.id.asc())
            .all()
        )

    def create_letterhead(self, lh: PrintLetterhead) -> PrintLetterhead:
        self.s.add(lh)
        self.s.flush([lh])
        return lh

    def update_letterhead_fields(self, lh: PrintLetterhead, data: Dict[str, Any]) -> None:
        for field, value in data.items():
            if hasattr(lh, field) and value is not None:
                setattr(lh, field, value)
        self.s.flush([lh])

    def clear_default_letterhead_for_company(self, company_id: int, exclude_id: Optional[int] = None) -> None:
        q = self.s.query(PrintLetterhead).filter(
            PrintLetterhead.company_id == company_id,
            PrintLetterhead.is_default_for_company.is_(True),
        )
        if exclude_id:
            q = q.filter(PrintLetterhead.id != exclude_id)
        q.update({PrintLetterhead.is_default_for_company: False})
        self.s.flush()

    # -----------------------------
    # Settings
    # -----------------------------

    def get_settings_by_id(self, settings_id: int) -> Optional[PrintSettings]:
        return self.s.get(PrintSettings, settings_id)

    def get_settings_for_company(self, company_id: Optional[int]) -> Optional[PrintSettings]:
        stmt = select(PrintSettings)
        if company_id is None:
            stmt = stmt.where(PrintSettings.company_id.is_(None))
        else:
            stmt = stmt.where(PrintSettings.company_id == company_id)
        return self.s.scalar(stmt)

    def create_settings(self, ps: PrintSettings) -> PrintSettings:
        self.s.add(ps)
        self.s.flush([ps])
        return ps

    def update_settings_fields(self, ps: PrintSettings, data: Dict[str, Any]) -> None:
        for field, value in data.items():
            if hasattr(ps, field) and value is not None:
                setattr(ps, field, value)
        self.s.flush([ps])

    # -----------------------------
    # Print Formats
    # -----------------------------

    def get_format_by_id(self, pf_id: int) -> Optional[PrintFormat]:
        return self.s.get(PrintFormat, pf_id)

    def get_format_by_code(self, *, doctype: str, code: str, company_id: Optional[int]) -> Optional[PrintFormat]:
        q = self.s.query(PrintFormat).filter(
            PrintFormat.doctype == doctype,
            PrintFormat.code == code,
            PrintFormat.is_disabled.is_(False),
        )
        if company_id is not None:
            q = q.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
        else:
            q = q.filter(PrintFormat.company_id.is_(None))
        return q.order_by(PrintFormat.company_id.is_(None).asc()).first()

    def list_formats_for_doctype(self, *, doctype: str, company_id: Optional[int]) -> list[PrintFormat]:
        q = self.s.query(PrintFormat).filter(
            PrintFormat.doctype == doctype,
            PrintFormat.is_disabled.is_(False),
        )
        if company_id is not None:
            q = q.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
        else:
            q = q.filter(PrintFormat.company_id.is_(None))
        return (
            q.order_by(
                PrintFormat.company_id.is_(None).asc(),          # company first
                PrintFormat.is_default_for_doctype.desc(),
                PrintFormat.is_standard.desc(),
                PrintFormat.id.asc(),
            )
            .all()
        )

    def create_format(self, pf: PrintFormat) -> PrintFormat:
        self.s.add(pf)
        self.s.flush([pf])
        return pf

    def update_format_fields(self, pf: PrintFormat, data: Dict[str, Any]) -> None:
        for field, value in data.items():
            if hasattr(pf, field) and value is not None:
                setattr(pf, field, value)
        self.s.flush([pf])

    def clear_default_for_doctype(
        self,
        *,
        doctype: str,
        company_id: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> None:
        q = self.s.query(PrintFormat).filter(PrintFormat.doctype == doctype, PrintFormat.is_default_for_doctype.is_(True))
        if company_id is None:
            q = q.filter(PrintFormat.company_id.is_(None))
        else:
            q = q.filter(PrintFormat.company_id == company_id)

        if exclude_id:
            q = q.filter(PrintFormat.id != exclude_id)

        q.update({PrintFormat.is_default_for_doctype: False})
        self.s.flush()

    # -----------------------------
    # Field Templates
    # -----------------------------

    def get_field_template_by_id(self, pfft_id: int) -> Optional[PrintFormatFieldTemplate]:
        return self.s.get(PrintFormatFieldTemplate, pfft_id)

    def create_field_template(self, ft: PrintFormatFieldTemplate) -> PrintFormatFieldTemplate:
        self.s.add(ft)
        self.s.flush([ft])
        return ft

    def update_field_template_fields(self, ft: PrintFormatFieldTemplate, data: Dict[str, Any]) -> None:
        for field, value in data.items():
            if hasattr(ft, field) and value is not None:
                setattr(ft, field, value)
        self.s.flush([ft])
