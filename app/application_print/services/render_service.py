# # # # app/application_print/services/render_service.py
#
# from __future__ import annotations
#
# import logging
# from dataclasses import dataclass
# from typing import Any, Dict, Optional, Tuple, List
#
# from jinja2 import Template
# from sqlalchemy import select
# from sqlalchemy.orm import Session
#
# from config.database import db
# from app.security.rbac_effective import AffiliationContext
# from app.application_print.registry.print_registry import get_print_config
# from app.application_print.models import (
#     PrintFormat,
#     PrintFormatType,
#     PrintSettings,
#     PrintStyle,
#     PrintLetterhead,
# )
#
# log = logging.getLogger(__name__)
#
#
# @dataclass
# class RenderMeta:
#     doctype: str
#     identifier: str
#     title: str
#     used_format_code: Optional[str]
#     used_style_code: Optional[str]
#     used_letterhead_id: Optional[int]
#
#
# class PrintRenderService:
#     """
#     Core print engine:
#
#     - Resolve PrintConfig (module/entity)
#     - Load document via loader
#     - Resolve PrintFormat (code/default)
#     - Resolve PrintSettings + PrintStyle (CSS theme)
#     - Resolve Letterhead HTML
#     - Render full HTML
#     """
#
#
#
#     # def render_document(self, *, module: str, entity: str, identifier: str, ctx: AffiliationContext,
#     #                     format_code: Optional[str] = None, letterhead_id: Optional[int] = None,
#     #                     with_letterhead: bool = True, style_code: Optional[str] = None) -> str:
#     #     try:
#     #         log.info(f"Rendering document for {module}/{entity} with identifier {identifier}")
#     #
#     #         # Call the rendering method with meta data
#     #         html, _meta = self.render_document_with_meta(module=module, entity=entity, identifier=identifier, ctx=ctx,
#     #                                                      format_code=format_code, letterhead_id=letterhead_id,
#     #                                                      with_letterhead=with_letterhead, style_code=style_code)
#     #
#     #         log.info(f"Document rendered successfully for {module}/{entity} with identifier {identifier}")
#     #         return html
#     #     except Exception as e:
#     #         log.error(f"Error rendering document {module}/{entity} with identifier {identifier}: {e}")
#     #         raise  # Reraise the exception to propagate it after logging
#
#     def render_document_with_meta(
#         self,
#         *,
#         module: str,
#         entity: str,
#         identifier: str | int,
#         ctx: AffiliationContext,
#         format_code: Optional[str] = None,
#         letterhead_id: Optional[int] = None,
#         with_letterhead: bool = True,
#         style_code: Optional[str] = None,
#     ) -> tuple[str, RenderMeta]:
#         s: Session = db.session
#         cfg = get_print_config(module, entity)
#
#         # 1) Load document (dict)
#         log.debug(f"Loading document for {module}/{entity} with identifier {identifier}")
#         doc = cfg.loader(s, ctx, identifier)
#         if not doc:
#             raise ValueError(f"Document '{identifier}' not found for {module}/{entity}.")
#
#         log.debug(f"Document loaded successfully for {module}/{entity} with identifier {identifier}")
#
#         company_id = getattr(ctx, "company_id", None)
#
#         # 2) Resolve print format (DB)
#         pf = self._resolve_print_format(
#             s=s,
#             doctype=cfg.doctype,
#             company_id=company_id,
#             format_code=format_code,
#         )
#         used_format_code = pf.code if pf else None
#
#         # Log format resolution
#         log.debug(f"Using print format: {used_format_code}")
#
#         # 3) Resolve style (explicit style_code > pf.print_style_id > PrintSettings default)
#         style_css, used_style_code = self._resolve_style_css(
#             s=s,
#             company_id=company_id,
#             pf=pf,
#             style_code=style_code,
#         )
#
#         log.debug(f"Using style code: {used_style_code}")
#
#         # 4) Resolve letterhead HTML (if enabled)
#         letter_head_html, used_letterhead_id = self._resolve_letterhead_html(
#             s=s,
#             company_id=company_id,
#             requested_letterhead_id=letterhead_id,
#             with_letterhead=with_letterhead,
#         )
#
#         # 5) Render inner HTML
#         if pf and pf.print_format_type == PrintFormatType.JINJA and pf.template_html:
#             log.debug(f"Rendering document using Jinja format")
#             inner_html = self._render_jinja_format(
#                 pf=pf,
#                 doc=doc,
#                 ctx=ctx,
#                 doctype=cfg.doctype,
#                 letter_head_html=letter_head_html,
#             )
#             title = f"{cfg.doctype} {identifier}"
#         else:
#             log.debug(f"Rendering document using standard builder format")
#             inner_html, title = self._render_standard_builder(
#                 module=module,
#                 entity=entity,
#                 doctype=cfg.doctype,
#                 doc=doc,
#             )
#
#         # 6) If format wants to disable global style, respect it
#         disable_global_style = bool((pf.layout_options or {}).get("disable_global_style")) if pf else False
#
#         log.debug(f"Disabling global style: {disable_global_style}")
#
#         html = self._wrap_html(
#             title=title,
#             inner_html=inner_html,
#             style_css=None if disable_global_style else style_css,
#         )
#
#         meta = RenderMeta(
#             doctype=cfg.doctype,
#             identifier=str(identifier),
#             title=title,
#             used_format_code=used_format_code,
#             used_style_code=used_style_code,
#             used_letterhead_id=used_letterhead_id,
#         )
#         return html, meta
#
#     # ---------------------------------------------------------
#     # FORMAT RESOLUTION
#     # ---------------------------------------------------------
#     def _resolve_print_format(
#             self,
#             *,
#             s: Session,
#             doctype: str,
#             company_id: Optional[int],
#             format_code: Optional[str],
#     ) -> Optional[PrintFormat]:
#         log.debug(f"Resolving print format for {doctype} with format_code {format_code}")
#
#         q = s.query(PrintFormat).filter(
#             PrintFormat.doctype == doctype,
#             PrintFormat.is_disabled.is_(False),
#         )
#
#         if company_id is not None:
#             from sqlalchemy import or_
#             q = q.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
#         else:
#             q = q.filter(PrintFormat.company_id.is_(None))
#
#         if format_code:
#             pf = q.filter(PrintFormat.code == format_code).first()
#             if pf:
#                 log.debug(f"Found print format: {pf.code}")
#                 return pf
#
#         pf = q.filter(PrintFormat.is_default_for_doctype.is_(True)).first()
#         if pf:
#             log.debug(f"Using default print format: {pf.code}")
#             return pf
#
#         log.debug("No matching print format found.")
#         return None
#
#     def _render_jinja_format(self, pf, doc, ctx, doctype, letter_head_html):
#         """
#         ERPNext-style Jinja renderer.
#         - No assumptions about doc structure
#         - Template controls layout & logic
#         """
#         try:
#             template = Template(pf.template_html or "")
#             return template.render(
#                 doc=doc,
#                 ctx=ctx,
#                 doctype=doctype,
#                 letter_head=letter_head_html,
#             )
#         except Exception as e:
#             log.exception(
#                 "Error rendering Jinja format | doctype=%s | format=%s",
#                 doctype,
#                 pf.slug,
#             )
#             raise
#     # ---------------------------------------------------------
#     # STYLE RESOLUTION
#     # ---------------------------------------------------------
#     def _resolve_style_css(
#         self,
#         *,
#         s: Session,
#         company_id: Optional[int],
#         pf: Optional[PrintFormat],
#         style_code: Optional[str],
#     ) -> tuple[Optional[str], Optional[str]]:
#         # 1) explicit style_code
#         if style_code:
#             from sqlalchemy import or_
#             q = s.query(PrintStyle).filter(PrintStyle.code == style_code, PrintStyle.is_disabled.is_(False))
#             if company_id is not None:
#                 q = q.filter(or_(PrintStyle.company_id == company_id, PrintStyle.company_id.is_(None)))
#             else:
#                 q = q.filter(PrintStyle.company_id.is_(None))
#             style = q.order_by(PrintStyle.company_id.is_(None).asc()).first()
#             if style:
#                 return style.css, style.code
#
#         # 2) print format override
#         if pf and pf.print_style_id:
#             style = s.get(PrintStyle, pf.print_style_id)
#             if style and not style.is_disabled:
#                 return style.css, style.code
#
#         # 3) PrintSettings default style
#         settings = None
#         if company_id is not None:
#             settings = s.scalar(select(PrintSettings).where(PrintSettings.company_id == company_id).limit(1))
#         if not settings:
#             settings = s.scalar(select(PrintSettings).where(PrintSettings.company_id.is_(None)).limit(1))
#
#         if not settings or not settings.default_print_style_id:
#             return None, None
#
#         style = s.get(PrintStyle, settings.default_print_style_id)
#         if not style or style.is_disabled:
#             return None, None
#
#         return style.css, style.code
#
#     # ---------------------------------------------------------
#     # LETTERHEAD RESOLUTION
#     # ---------------------------------------------------------
#     def _resolve_letterhead_html(
#         self,
#         *,
#         s: Session,
#         company_id: Optional[int],
#         requested_letterhead_id: Optional[int],
#         with_letterhead: bool,
#     ) -> tuple[str, Optional[int]]:
#         if not with_letterhead:
#             return "", None
#         if not company_id:
#             return "", None
#
#         lh: Optional[PrintLetterhead] = None
#         if requested_letterhead_id:
#             lh = s.get(PrintLetterhead, requested_letterhead_id)
#             if lh and (lh.company_id != company_id or lh.is_disabled):
#                 lh = None
#
#         if not lh:
#             lh = (
#                 s.query(PrintLetterhead)
#                 .filter(
#                     PrintLetterhead.company_id == company_id,
#                     PrintLetterhead.is_disabled.is_(False),
#                     PrintLetterhead.is_default_for_company.is_(True),
#                 )
#                 .first()
#             )
#
#         if not lh:
#             return "", None
#
#         # prefer HTML header; image not handled here
#         html = lh.header_html or ""
#         return html, lh.id
#
#     # ---------------------------------------------------------
#     # JINJA FORMAT RENDER
#     # ---------------------------------------------------------
#     # def _render_jinja_format(self, pf, doc, ctx, doctype, letter_head_html):
#     #     try:
#     #         log.info(f"Rendering Jinja format for doctype: {doctype}, identifier: {doc.get('id', 'unknown')}")
#     #
#     #         # Log the data being passed to the template for debugging
#     #         log.debug(f"Data passed to Jinja template: {doc}")
#     #
#     #         # Check if `items` is iterable and not a method
#     #         if not hasattr(doc, 'items') or not isinstance(doc['items'], (list, tuple)):
#     #             log.error(f"Invalid data for 'items': {doc.get('items')}. Expected a list or tuple.")
#     #             raise ValueError("The 'items' field should be a list or tuple.")
#     #
#     #         # Ensure that 'items' field is valid and can be iterated
#     #         template = Template(pf.template_html or "")
#     #         html = template.render(
#     #             doc=doc,
#     #             ctx=ctx,
#     #             doctype=doctype,
#     #             letter_head=letter_head_html,  # Your Djibouti template uses this
#     #         )
#     #         return html
#     #     except Exception as e:
#     #         log.error(f"Error in _render_jinja_format for {doctype} {doc.get('id', 'unknown')}: {e}")
#     #         raise
#
#     # ---------------------------------------------------------
#     # STANDARD BUILDER (GENERIC)
#     # ---------------------------------------------------------
#     def _split_doc_for_standard(
#         self,
#         doc: Dict[str, Any],
#     ) -> Tuple[List[Tuple[str, Any]], List[Tuple[str, List[Dict[str, Any]]]]]:
#         scalars: list[tuple[str, Any]] = []
#         sections: list[tuple[str, list[dict[str, Any]]]] = []
#
#         for key, value in doc.items():
#             if key in {"_meta", "_links"}:
#                 continue
#
#             if isinstance(value, (list, tuple)):
#                 rows = [r for r in value if isinstance(r, dict)]
#                 if rows:
#                     sections.append((key, rows))
#             elif isinstance(value, dict):
#                 for sub_k, sub_v in value.items():
#                     scalars.append((f"{key}.{sub_k}", sub_v))
#             else:
#                 scalars.append((key, value))
#
#         return scalars, sections
#
#     def _render_standard_builder(
#         self,
#         *,
#         module: str,
#         entity: str,
#         doctype: str,
#         doc: Dict[str, Any],
#     ) -> Tuple[str, str]:
#         scalars, sections = self._split_doc_for_standard(doc)
#
#         title = f"{doctype or entity}".replace("_", " ")
#         subtitle = doc.get("code") or doc.get("name") or doc.get("id")
#
#         tmpl = Template(
#             """
# <div class="print-format">
#   <div class="print-heading">
#     <h2>{{ title }}</h2>
#     {% if subtitle %}
#       <div class="small">{{ subtitle }}</div>
#     {% endif %}
#   </div>
#
#   {% if scalars %}
#     <table class="table table-bordered meta-table">
#       <tbody>
#         {% for label, value in scalars %}
#           <tr>
#             <th style="width: 30%; text-transform: capitalize;">{{ label.replace('_', ' ') }}</th>
#             <td>{{ value }}</td>
#           </tr>
#         {% endfor %}
#       </tbody>
#     </table>
#   {% endif %}
#
#   {% for section_name, rows in sections %}
#     <h3 style="margin-top: 16px; margin-bottom: 4px; text-transform: capitalize;">
#       {{ section_name.replace('_', ' ') }}
#     </h3>
#     <table class="table table-bordered">
#       <thead>
#         <tr>
#           {% set all_keys = [] %}
#           {% for r in rows %}
#             {% for k in r.keys() %}
#               {% if k not in all_keys %}
#                 {% set _ = all_keys.append(k) %}
#               {% endif %}
#             {% endfor %}
#           {% endfor %}
#           {% for k in all_keys %}
#             <th style="text-transform: capitalize;">{{ k.replace('_', ' ') }}</th>
#           {% endfor %}
#         </tr>
#       </thead>
#       <tbody>
#         {% for r in rows %}
#           <tr>
#             {% for k in all_keys %}
#               <td>{{ r.get(k) }}</td>
#             {% endfor %}
#           </tr>
#         {% endfor %}
#       </tbody>
#     </table>
#   {% endfor %}
# </div>
#             """.strip()
#         )
#
#         inner_html = tmpl.render(title=title, subtitle=subtitle, scalars=scalars, sections=sections)
#         return inner_html, f"{title} {subtitle or ''}".strip()
#
#     # ---------------------------------------------------------
#     # HTML WRAPPER
#     # ---------------------------------------------------------
#     def _wrap_html(
#         self,
#         *,
#         title: str,
#         inner_html: str,
#         style_css: Optional[str],
#     ) -> str:
#         base_body_css = """
# body {
#   margin: 0;
#   padding: 16px;
#   font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
#   font-size: 13px;
#   color: #222;
# }
# .print-format {
#   font-size: 13px;
# }
#         """.strip()
#
#         return f"""<!DOCTYPE html>
# <html>
# <head>
#   <meta charset="utf-8" />
#   <title>{title}</title>
#   <style>{base_body_css}</style>
#   {f"<style>{style_css}</style>" if style_css else ""}
# </head>
# <body>
# {inner_html}
# </body>
# </html>
# """.strip()
#
#
# print_render_service = PrintRenderService()
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from jinja2 import Template
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.database import db
from app.security.rbac_effective import AffiliationContext
from app.application_print.registry.print_registry import get_print_config
from app.application_print.models import (
    PrintFormat,
    PrintFormatType,
    PrintSettings,
    PrintStyle,
    PrintLetterhead,
)

log = logging.getLogger(__name__)


@dataclass
class RenderMeta:
    doctype: str
    identifier: str
    title: str
    used_format_code: Optional[str]
    used_style_code: Optional[str]
    used_letterhead_id: Optional[int]


class PrintRenderService:
    """
    Core print engine
    """

    def _normalize_doc(self, doc: Any) -> Dict[str, Any]:
        """
        Your Jinja templates use doc.get(...), doc['items'], etc.
        If the loader returns a Pydantic model / SQLAlchemy object, normalize it into a dict.
        """
        if doc is None:
            return {}

        if isinstance(doc, dict):
            return doc

        # Pydantic v2
        if hasattr(doc, "model_dump"):
            try:
                return doc.model_dump()
            except Exception:
                pass

        # custom serializer
        if hasattr(doc, "to_dict"):
            try:
                return doc.to_dict()
            except Exception:
                pass

        # dataclass
        if hasattr(doc, "__dataclass_fields__"):
            try:
                return {k: getattr(doc, k) for k in doc.__dataclass_fields__.keys()}
            except Exception:
                pass

        # SQLAlchemy-ish / generic object
        if hasattr(doc, "__dict__"):
            try:
                return {k: v for k, v in doc.__dict__.items() if not k.startswith("_")}
            except Exception:
                pass

        # last resort
        return {"value": doc}

    def render_document(
        self,
        *,
        module: str,
        entity: str,
        identifier: str,
        ctx: AffiliationContext,
        format_code: Optional[str] = None,
        letterhead_id: Optional[int] = None,
        with_letterhead: bool = True,
        style_code: Optional[str] = None,
        page_size: str = "A4",
        orientation: str = "Portrait",
    ) -> str:
        html, _meta = self.render_document_with_meta(
            module=module,
            entity=entity,
            identifier=identifier,
            ctx=ctx,
            format_code=format_code,
            letterhead_id=letterhead_id,
            with_letterhead=with_letterhead,
            style_code=style_code,
            page_size=page_size,
            orientation=orientation,
        )
        return html

    def render_document_with_meta(
        self,
        *,
        module: str,
        entity: str,
        identifier: str | int,
        ctx: AffiliationContext,
        format_code: Optional[str] = None,
        letterhead_id: Optional[int] = None,
        with_letterhead: bool = True,
        style_code: Optional[str] = None,
        page_size: str = "A4",
        orientation: str = "Portrait",
    ) -> tuple[str, RenderMeta]:
        s: Session = db.session
        cfg = get_print_config(module, entity)

        raw_doc = cfg.loader(s, ctx, identifier)
        doc = self._normalize_doc(raw_doc)

        if not doc:
            raise ValueError(f"Document '{identifier}' not found for {module}/{entity}.")

        company_id = getattr(ctx, "company_id", None)

        pf = self._resolve_print_format(
            s=s,
            doctype=cfg.doctype,
            company_id=company_id,
            format_code=format_code,
        )
        used_format_code = pf.code if pf else None

        style_css, used_style_code = self._resolve_style_css(
            s=s,
            company_id=company_id,
            pf=pf,
            style_code=style_code,
        )

        letter_head_html, used_letterhead_id = self._resolve_letterhead_html(
            s=s,
            company_id=company_id,
            requested_letterhead_id=letterhead_id,
            with_letterhead=with_letterhead,
        )

        if pf and pf.print_format_type == PrintFormatType.JINJA and pf.template_html:
            inner_html = self._render_jinja_format(
                pf=pf,
                doc=doc,
                ctx=ctx,
                doctype=cfg.doctype,
                letter_head_html=letter_head_html,
            )
            title = f"{cfg.doctype} {identifier}"
        else:
            inner_html, title = self._render_standard_builder(
                module=module,
                entity=entity,
                doctype=cfg.doctype,
                doc=doc,
            )

        disable_global_style = bool((pf.layout_options or {}).get("disable_global_style")) if pf else False
        page_css = self._page_css(page_size=page_size, orientation=orientation)

        html = self._wrap_html(
            title=title,
            inner_html=inner_html,
            style_css=None if disable_global_style else style_css,
            page_css=page_css,
        )

        meta = RenderMeta(
            doctype=cfg.doctype,
            identifier=str(identifier),
            title=title,
            used_format_code=used_format_code,
            used_style_code=used_style_code,
            used_letterhead_id=used_letterhead_id,
        )
        return html, meta

    def _page_css(self, page_size: str, orientation: str) -> str:
        size = (page_size or "A4").strip()
        orient = "landscape" if (orientation or "Portrait").lower().startswith("land") else "portrait"
        return f"""
@page {{
  size: {size} {orient};
  margin: 10mm 10mm 10mm 10mm;
}}
""".strip()

    def _wrap_html(
        self,
        *,
        title: str,
        inner_html: str,
        style_css: Optional[str],
        page_css: Optional[str] = None,
    ) -> str:
        base_body_css = """
body {
  margin: 0;
  padding: 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 13px;
  color: #222;
}
.print-format { font-size: 13px; }
""".strip()

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>{base_body_css}</style>
  {f"<style>{page_css}</style>" if page_css else ""}
  {f"<style>{style_css}</style>" if style_css else ""}
</head>
<body>
{inner_html}
</body>
</html>
""".strip()

    def _resolve_print_format(
        self,
        *,
        s: Session,
        doctype: str,
        company_id: Optional[int],
        format_code: Optional[str],
    ) -> Optional[PrintFormat]:
        q = s.query(PrintFormat).filter(
            PrintFormat.doctype == doctype,
            PrintFormat.is_disabled.is_(False),
        )

        if company_id is not None:
            from sqlalchemy import or_
            q = q.filter(or_(PrintFormat.company_id == company_id, PrintFormat.company_id.is_(None)))
        else:
            q = q.filter(PrintFormat.company_id.is_(None))

        if format_code:
            pf = q.filter(PrintFormat.code == format_code).first()
            if pf:
                return pf

        pf = q.filter(PrintFormat.is_default_for_doctype.is_(True)).first()
        if pf:
            return pf

        return None

    def _render_jinja_format(self, pf, doc, ctx, doctype, letter_head_html):
        try:
            template = Template(pf.template_html or "")
            return template.render(
                doc=doc,
                ctx=ctx,
                doctype=doctype,
                letter_head=letter_head_html,
            )
        except Exception as e:
            fmt = getattr(pf, "code", None) or "unknown"
            log.exception("Jinja render failed doctype=%s format=%s err=%s", doctype, fmt, e)
            raise

    def _resolve_style_css(
        self,
        *,
        s: Session,
        company_id: Optional[int],
        pf: Optional[PrintFormat],
        style_code: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        if style_code:
            from sqlalchemy import or_
            q = s.query(PrintStyle).filter(PrintStyle.code == style_code, PrintStyle.is_disabled.is_(False))
            if company_id is not None:
                q = q.filter(or_(PrintStyle.company_id == company_id, PrintStyle.company_id.is_(None)))
            else:
                q = q.filter(PrintStyle.company_id.is_(None))
            style = q.order_by(PrintStyle.company_id.is_(None).asc()).first()
            if style:
                return style.css, style.code

        if pf and pf.print_style_id:
            style = s.get(PrintStyle, pf.print_style_id)
            if style and not style.is_disabled:
                return style.css, style.code

        settings = None
        if company_id is not None:
            settings = s.scalar(select(PrintSettings).where(PrintSettings.company_id == company_id).limit(1))
        if not settings:
            settings = s.scalar(select(PrintSettings).where(PrintSettings.company_id.is_(None)).limit(1))

        if not settings or not settings.default_print_style_id:
            return None, None

        style = s.get(PrintStyle, settings.default_print_style_id)
        if not style or style.is_disabled:
            return None, None

        return style.css, style.code

    def _resolve_letterhead_html(
        self,
        *,
        s: Session,
        company_id: Optional[int],
        requested_letterhead_id: Optional[int],
        with_letterhead: bool,
    ) -> tuple[str, Optional[int]]:
        if not with_letterhead or not company_id:
            return "", None

        lh: Optional[PrintLetterhead] = None
        if requested_letterhead_id:
            lh = s.get(PrintLetterhead, requested_letterhead_id)
            if lh and (lh.company_id != company_id or lh.is_disabled):
                lh = None

        if not lh:
            lh = (
                s.query(PrintLetterhead)
                .filter(
                    PrintLetterhead.company_id == company_id,
                    PrintLetterhead.is_disabled.is_(False),
                    PrintLetterhead.is_default_for_company.is_(True),
                )
                .first()
            )

        if not lh:
            return "", None

        return (lh.header_html or ""), lh.id

    def _split_doc_for_standard(
        self,
        doc: Dict[str, Any],
    ) -> Tuple[List[Tuple[str, Any]], List[Tuple[str, List[Dict[str, Any]]]]]:
        scalars: list[tuple[str, Any]] = []
        sections: list[tuple[str, list[dict[str, Any]]]] = []

        for key, value in doc.items():
            if key in {"_meta", "_links"}:
                continue

            if isinstance(value, (list, tuple)):
                rows = [r for r in value if isinstance(r, dict)]
                if rows:
                    sections.append((key, rows))
            elif isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    scalars.append((f"{key}.{sub_k}", sub_v))
            else:
                scalars.append((key, value))

        return scalars, sections

    def _render_standard_builder(
        self,
        *,
        module: str,
        entity: str,
        doctype: str,
        doc: Dict[str, Any],
    ) -> Tuple[str, str]:
        scalars, sections = self._split_doc_for_standard(doc)

        title = f"{doctype or entity}".replace("_", " ")
        subtitle = doc.get("code") or doc.get("name") or doc.get("id")

        tmpl = Template(
            """
<div class="print-format">
  <div class="print-heading">
    <h2>{{ title }}</h2>
    {% if subtitle %}<div class="small">{{ subtitle }}</div>{% endif %}
  </div>

  {% if scalars %}
    <table class="table table-bordered meta-table">
      <tbody>
        {% for label, value in scalars %}
          <tr>
            <th style="width: 30%; text-transform: capitalize;">{{ label.replace('_', ' ') }}</th>
            <td>{{ value }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}

  {% for section_name, rows in sections %}
    <h3 style="margin-top: 16px; margin-bottom: 4px; text-transform: capitalize;">
      {{ section_name.replace('_', ' ') }}
    </h3>
    <table class="table table-bordered">
      <thead>
        <tr>
          {% set all_keys = [] %}
          {% for r in rows %}
            {% for k in r.keys() %}
              {% if k not in all_keys %}
                {% set _ = all_keys.append(k) %}
              {% endif %}
            {% endfor %}
          {% endfor %}
          {% for k in all_keys %}
            <th style="text-transform: capitalize;">{{ k.replace('_', ' ') }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
          <tr>
            {% for k in all_keys %}
              <td>{{ r.get(k) }}</td>
            {% endfor %}
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endfor %}
</div>
            """.strip()
        )

        inner_html = tmpl.render(title=title, subtitle=subtitle, scalars=scalars, sections=sections)
        return inner_html, f"{title} {subtitle or ''}".strip()


print_render_service = PrintRenderService()
