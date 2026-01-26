# app/application_print/services/config_service.py
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.database import db
from app.application_print.models import (
    PrintLetterhead,
    PrintStyle,
    PrintSettings,
    PrintFormat,
    PrintFormatType,
    PrintFormatFieldTemplate,
)
from app.application_print.repository.print_repo import PrintRepository
from app.application_print.print_config import (
    PrintStyleCreate,
    PrintStyleUpdate,
    PrintLetterheadCreate,
    PrintLetterheadUpdate,
    PrintSettingsCreate,
    PrintSettingsUpdate,
    PrintFormatCreate,
    PrintFormatUpdate,
    PrintFormatFieldTemplateCreate,
    PrintFormatFieldTemplateUpdate,
)
from app.business_validation.item_validation import BizValidationError
from app.security.rbac_effective import AffiliationContext
from app.security.rbac_guards import ensure_scope_by_ids

log = logging.getLogger(__name__)


class PrintConfigService:
    def __init__(self, repo: Optional[PrintRepository] = None, session: Optional[Session] = None):
        self.repo = repo or PrintRepository(session or db.session)
        self.s: Session = self.repo.s

    # ----------------------------------------------------
    # tx helpers
    # ----------------------------------------------------
    @property
    def _in_nested_tx(self) -> bool:
        try:
            fn = getattr(self.s, "in_nested_transaction", None)
            if callable(fn):
                return bool(fn())
        except Exception:
            pass

        tx = getattr(self.s, "transaction", None)
        if tx is None:
            return False
        if getattr(tx, "nested", False):
            return True
        parent = getattr(tx, "parent", None)
        while parent is not None:
            if getattr(parent, "nested", False):
                return True
            parent = parent.parent
        return False

    def _commit_or_flush(self) -> None:
        if self._in_nested_tx:
            self.s.flush()
        else:
            self.s.commit()

    def _rollback_if_top_level(self) -> None:
        if self._in_nested_tx:
            return
        self.s.rollback()

    # ----------------------------------------------------
    # Styles
    # ----------------------------------------------------
    def create_style(
        self,
        *,
        payload: PrintStyleCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintStyle]]:
        try:
            if payload.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=payload.company_id,
                    target_branch_id=None,
                )

            style = PrintStyle(
                name=payload.name,
                code=payload.code,
                description=payload.description,
                css=payload.css,
                company_id=payload.company_id,
                is_disabled=payload.is_disabled,
                is_default_global=payload.is_default_global,
            )
            self.repo.create_style(style)

            if style.is_default_global:
                self.repo.clear_default_global_style(exclude_id=style.id)

            self._commit_or_flush()
            return True, "Print Style created", style

        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "unique" in msg and "code" in msg:
                return False, "Print Style code already exists.", None
            return False, "Integrity error while creating Print Style.", None
        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_style failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Print Style.", None

    def update_style(
        self,
        *,
        style_id: int,
        payload: PrintStyleUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintStyle]]:
        try:
            style = self.repo.get_style_by_id(style_id)
            if not style:
                return False, "Print Style not found.", None

            if style.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=style.company_id,
                    target_branch_id=None,
                )

            data = payload.dict(exclude_unset=True)
            self.repo.update_style_fields(style, data)

            if data.get("is_default_global"):
                self.repo.clear_default_global_style(exclude_id=style.id)

            self._commit_or_flush()
            return True, "Print Style updated", style

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_style failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Print Style.", None

    # ----------------------------------------------------
    # Letterheads
    # ----------------------------------------------------
    def create_letterhead(
        self,
        *,
        payload: PrintLetterheadCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintLetterhead]]:
        try:
            ensure_scope_by_ids(
                context=context,
                target_company_id=payload.company_id,
                target_branch_id=None,
            )

            lh = PrintLetterhead(
                company_id=payload.company_id,
                name=payload.name,
                code=payload.code,
                header_based_on_image=payload.header_based_on_image,
                header_image_key=payload.header_image_key,
                header_image_height=payload.header_image_height,
                header_image_width=payload.header_image_width,
                header_align=payload.header_align,
                header_html=payload.header_html,
                footer_based_on_image=payload.footer_based_on_image,
                footer_image_key=payload.footer_image_key,
                footer_image_height=payload.footer_image_height,
                footer_image_width=payload.footer_image_width,
                footer_align=payload.footer_align,
                footer_html=payload.footer_html,
                is_disabled=payload.is_disabled,
                is_default_for_company=payload.is_default_for_company,
            )
            self.repo.create_letterhead(lh)

            if lh.is_default_for_company:
                self.repo.clear_default_letterhead_for_company(
                    company_id=lh.company_id,
                    exclude_id=lh.id,
                )

            self._commit_or_flush()
            return True, "Letterhead created", lh

        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "unique" in msg and "code" in msg:
                return False, "Letterhead code already exists.", None
            return False, "Integrity error while creating Letterhead.", None
        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_letterhead failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Letterhead.", None

    def update_letterhead(
        self,
        *,
        letterhead_id: int,
        payload: PrintLetterheadUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintLetterhead]]:
        try:
            lh = self.repo.get_letterhead_by_id(letterhead_id)
            if not lh:
                return False, "Letterhead not found.", None

            ensure_scope_by_ids(
                context=context,
                target_company_id=lh.company_id,
                target_branch_id=None,
            )

            data = payload.dict(exclude_unset=True)
            self.repo.update_letterhead_fields(lh, data)

            if data.get("is_default_for_company"):
                self.repo.clear_default_letterhead_for_company(
                    company_id=lh.company_id,
                    exclude_id=lh.id,
                )

            self._commit_or_flush()
            return True, "Letterhead updated", lh

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_letterhead failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Letterhead.", None

    # ----------------------------------------------------
    # Settings
    # ----------------------------------------------------
    def create_settings(
        self,
        *,
        payload: PrintSettingsCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintSettings]]:
        try:
            if payload.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=payload.company_id,
                    target_branch_id=None,
                )

            existing = self.repo.get_settings_for_company(payload.company_id)
            if existing:
                raise BizValidationError("Print Settings already exist for this Company.")

            ps = PrintSettings(
                company_id=payload.company_id,
                send_print_as_pdf=payload.send_print_as_pdf,
                send_email_print_attachments_as_pdf=payload.send_email_print_attachments_as_pdf,
                repeat_header_footer_in_pdf=payload.repeat_header_footer_in_pdf,
                pdf_page_size=payload.pdf_page_size,
                print_with_letterhead=payload.print_with_letterhead,
                compact_item_print=payload.compact_item_print,
                print_uom_after_qty=payload.print_uom_after_qty,
                allow_print_for_draft=payload.allow_print_for_draft,
                always_add_draft_heading=payload.always_add_draft_heading,
                allow_page_break_inside_tables=payload.allow_page_break_inside_tables,
                allow_print_for_cancelled=payload.allow_print_for_cancelled,
                print_taxes_with_zero_amount=payload.print_taxes_with_zero_amount,
                enable_raw_printing=payload.enable_raw_printing,
                default_print_style_id=payload.default_print_style_id,
                default_font_family=payload.default_font_family,
                default_font_size_pt=payload.default_font_size_pt,
                default_language=payload.default_language,
                additional_options=payload.additional_options,
            )
            self.repo.create_settings(ps)
            self._commit_or_flush()
            return True, "Print Settings created", ps

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_settings failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Print Settings.", None

    def update_settings(
        self,
        *,
        settings_id: int,
        payload: PrintSettingsUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintSettings]]:
        try:
            ps = self.repo.get_settings_by_id(settings_id)
            if not ps:
                return False, "Print Settings not found.", None

            if ps.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=ps.company_id,
                    target_branch_id=None,
                )

            data = payload.dict(exclude_unset=True)
            self.repo.update_settings_fields(ps, data)

            self._commit_or_flush()
            return True, "Print Settings updated", ps

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_settings failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Print Settings.", None

    # ----------------------------------------------------
    # Print Formats
    # ----------------------------------------------------
    def create_print_format(
        self,
        *,
        payload: PrintFormatCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintFormat]]:
        try:
            if payload.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=payload.company_id,
                    target_branch_id=None,
                )

            if payload.print_format_type == PrintFormatType.JINJA and not payload.template_html:
                raise BizValidationError("Template HTML is required for Jinja Print Formats.")

            pf = PrintFormat(
                doctype=payload.doctype,
                module=payload.module,
                name=payload.name,
                code=payload.code,
                company_id=payload.company_id,
                default_print_language=payload.default_print_language,
                is_standard=payload.is_standard,
                is_default_for_doctype=payload.is_default_for_doctype,
                is_disabled=payload.is_disabled,
                print_format_type=payload.print_format_type,
                custom_format=payload.custom_format,
                raw_printing=payload.raw_printing,
                margin_top_mm=payload.margin_top_mm,
                margin_bottom_mm=payload.margin_bottom_mm,
                margin_left_mm=payload.margin_left_mm,
                margin_right_mm=payload.margin_right_mm,
                font_size_pt=payload.font_size_pt,
                google_font=payload.google_font,
                align_labels_to_right=payload.align_labels_to_right,
                show_section_headings=payload.show_section_headings,
                show_line_breaks_after_sections=payload.show_line_breaks_after_sections,
                template_html=payload.template_html,
                custom_css=payload.custom_css,
                external_url=payload.external_url,
                raw_payload_template=payload.raw_payload_template,
                default_letterhead_id=payload.default_letterhead_id,
                print_style_id=payload.print_style_id,
                layout_options=payload.layout_options,
            )
            self.repo.create_format(pf)

            if pf.is_default_for_doctype:
                self.repo.clear_default_for_doctype(
                    doctype=pf.doctype,
                    company_id=pf.company_id,
                    exclude_id=pf.id,
                )

            self._commit_or_flush()
            return True, "Print Format created", pf

        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "unique" in msg and "code" in msg:
                return False, "Print Format code already exists.", None
            return False, "Integrity error while creating Print Format.", None
        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_print_format failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Print Format.", None

    def update_print_format(
        self,
        *,
        print_format_id: int,
        payload: PrintFormatUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintFormat]]:
        try:
            pf = self.repo.get_format_by_id(print_format_id)
            if not pf:
                return False, "Print Format not found.", None

            if pf.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=pf.company_id,
                    target_branch_id=None,
                )

            data = payload.dict(exclude_unset=True)

            if data.get("print_format_type", pf.print_format_type) == PrintFormatType.JINJA:
                tmpl = data.get("template_html", pf.template_html)
                if not tmpl:
                    raise BizValidationError("Template HTML is required for Jinja Print Formats.")

            self.repo.update_format_fields(pf, data)

            if data.get("is_default_for_doctype"):
                self.repo.clear_default_for_doctype(
                    doctype=pf.doctype,
                    company_id=pf.company_id,
                    exclude_id=pf.id,
                )

            self._commit_or_flush()
            return True, "Print Format updated", pf

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_print_format failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Print Format.", None

    # ----------------------------------------------------
    # Field Templates
    # ----------------------------------------------------
    def create_field_template(
        self,
        *,
        payload: PrintFormatFieldTemplateCreate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintFormatFieldTemplate]]:
        try:
            pf = self.repo.get_format_by_id(payload.print_format_id)
            if not pf:
                raise BizValidationError("Parent Print Format not found.")

            if pf.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=pf.company_id,
                    target_branch_id=None,
                )

            ft = PrintFormatFieldTemplate(
                print_format_id=payload.print_format_id,
                doctype=payload.doctype,
                field_name=payload.field_name,
                field_label=payload.field_label,
                description=payload.description,
                template_html=payload.template_html,
                is_default_for_field=payload.is_default_for_field,
                language=payload.language,
            )
            self.repo.create_field_template(ft)
            self._commit_or_flush()
            return True, "Field Template created", ft

        except IntegrityError as e:
            self._rollback_if_top_level()
            msg = (str(e.orig) if getattr(e, "orig", None) else str(e)).lower()
            if "uq_pfft_format_field_lang" in msg:
                return False, "Field Template already exists for this field/language.", None
            return False, "Integrity error while creating Field Template.", None
        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("create_field_template failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while creating Field Template.", None

    def update_field_template(
        self,
        *,
        field_template_id: int,
        payload: PrintFormatFieldTemplateUpdate,
        context: AffiliationContext,
    ) -> Tuple[bool, str, Optional[PrintFormatFieldTemplate]]:
        try:
            ft = self.repo.get_field_template_by_id(field_template_id)
            if not ft:
                return False, "Field Template not found.", None

            pf = ft.print_format
            if pf and pf.company_id:
                ensure_scope_by_ids(
                    context=context,
                    target_company_id=pf.company_id,
                    target_branch_id=None,
                )

            data = payload.dict(exclude_unset=True)
            self.repo.update_field_template_fields(ft, data)

            self._commit_or_flush()
            return True, "Field Template updated", ft

        except BizValidationError as e:
            self._rollback_if_top_level()
            return False, str(e), None
        except Exception as e:
            log.exception("update_field_template failed: %s", e)
            self._rollback_if_top_level()
            return False, "Unexpected error while updating Field Template.", None
