# app/application_meta/service.py
from __future__ import annotations
from typing import Optional

from werkzeug.exceptions import NotFound, BadRequest
from sqlalchemy import select, and_

from app.application_meta.repository import meta_repository
from app.application_meta.schemas import (
    DoctypeMetaOut,
    DocFieldOut,
    DocPermissionOut,
    DocLinkOut,
    ListViewUpdateIn,
    ListViewFieldUpdateIn,
)
from app.application_meta.models import DocField

from app.application_rbac.permission_matrix_service import permission_matrix_service
from app.security.rbac_effective import AffiliationContext


class MetaService:
    def get_doctype_meta(
        self,
        *,
        name: str,
        ctx: AffiliationContext,
        company_id: Optional[int] = None,
    ) -> DoctypeMetaOut:
        """
        Build the full meta response for a doctype, with company-specific overrides:

        - Structure + fields from application_meta (Doctype, DocField, DocLink)
        - Permissions grid derived from the real RBAC engine (Role / Permission / RolePermission)
        """
        dt = meta_repository.get_doctype_by_name(name)
        if not dt:
            raise NotFound(f"Doctype {name!r} not found")

        # If company_id not passed explicitly, use from context (most common)
        if company_id is None:
            company_id = getattr(ctx, "company_id", None)

        # 1) Fields with company-specific overrides (DocField.company_id = NULL or company_id)
        fields = meta_repository.get_effective_fields(
            doctype_id=dt.id,
            company_id=company_id,
        )

        # 2) Permission grid VIEW, built from RBAC (no docpermissions table)
        permissions: list[DocPermissionOut] = permission_matrix_service.get_role_matrix_for_doctype(
            doctype_name=dt.name,
            company_id=company_id,
        )

        # 3) Linked doctypes (for related docs section in UI)
        links = meta_repository.get_links(parent_doctype_name=dt.name)

        return DoctypeMetaOut(
            name=dt.name,
            label=dt.label,
            module=dt.module,
            table_name=dt.table_name,
            icon=dt.icon,
            is_child=dt.is_child,
            is_single=dt.is_single,
            is_tree=dt.is_tree,
            is_submittable=dt.is_submittable,
            track_changes=dt.track_changes,
            track_seen=dt.track_seen,
            track_views=dt.track_views,
            quick_entry=dt.quick_entry,
            description=dt.description,
            fields=[
                DocFieldOut(
                    fieldname=f.fieldname,
                    label=f.label,
                    fieldtype=f.fieldtype,
                    options=f.options,
                    default=f.default,
                    reqd=f.reqd,
                    read_only=f.read_only,
                    hidden=f.hidden,
                    in_list_view=f.in_list_view,
                    in_filter=f.in_filter,
                    in_quick_entry=f.in_quick_entry,
                    idx=f.idx,
                    description=f.description,
                )
                for f in fields
            ],
            # Already DocPermissionOut list from RBAC
            permissions=permissions,
            links=[
                DocLinkOut(
                    parent_doctype=l.parent_doctype,
                    link_doctype=l.link_doctype,
                    link_fieldname=l.link_fieldname,
                    group_label=l.group_label,
                )
                for l in links
            ],
        )

    # ------------------------------------------------------------------
    # Company-specific list view customization (Frappe-like "Customize")
    # ------------------------------------------------------------------
    def update_list_view_config(
        self,
        *,
        name: str,
        ctx: AffiliationContext,
        payload: ListViewUpdateIn,
    ) -> None:
        """
        Applies company-specific DocField overrides for list view (and optional filter/quick-entry flags).

        - Base DocField rows have company_id = NULL.
        - Overrides have company_id = <company> and same fieldname.
        - This does NOT change security; only list-view presentation.
        """
        dt = meta_repository.get_doctype_by_name(name)
        if not dt:
            raise NotFound(f"Doctype {name!r} not found")

        # Determine which company we are updating for
        target_company_id: Optional[int] = payload.company_id or getattr(ctx, "company_id", None)
        if not target_company_id:
            raise BadRequest("company_id is required (either in payload or in context).")

        # Prevent tenant A customizing tenant B (simple guard)
        ctx_company_id = getattr(ctx, "company_id", None)
        if payload.company_id and ctx_company_id and payload.company_id != ctx_company_id:
            raise BadRequest("You cannot customize list view for another company.")

        session = meta_repository.session

        # 1) Load base fields (company_id IS NULL) for this doctype
        base_stmt = (
            select(DocField)
            .where(
                and_(
                    DocField.doctype_id == dt.id,
                    DocField.company_id.is_(None),
                )
            )
        )
        base_fields = session.execute(base_stmt).scalars().all()
        base_by_name = {f.fieldname: f for f in base_fields}

        # 2) Load existing overrides for this company
        override_stmt = (
            select(DocField)
            .where(
                and_(
                    DocField.doctype_id == dt.id,
                    DocField.company_id == target_company_id,
                )
            )
        )
        overrides = session.execute(override_stmt).scalars().all()
        overrides_by_name = {f.fieldname: f for f in overrides}

        # 3) Apply updates field by field
        for upd in payload.fields:
            fieldname = upd.fieldname

            base_field = base_by_name.get(fieldname)
            override_field = overrides_by_name.get(fieldname)

            if not base_field and not override_field:
                # Unknown fieldname: skip silently or log
                continue

            if override_field is None:
                # Create a new override based on base_field or, if ever present, an existing override.
                template = override_field or base_field
                if not template:
                    continue

                override_field = DocField(
                    doctype_id=dt.id,
                    fieldname=template.fieldname,
                    label=template.label,
                    fieldtype=template.fieldtype,
                    options=template.options,
                    default=template.default,
                    reqd=template.reqd,
                    read_only=template.read_only,
                    hidden=template.hidden,
                    in_list_view=template.in_list_view,
                    in_filter=template.in_filter,
                    in_quick_entry=template.in_quick_entry,
                    idx=template.idx,
                    description=template.description,
                    company_id=target_company_id,
                )
                session.add(override_field)
                overrides_by_name[fieldname] = override_field

            # Now apply the updates on the override
            if upd.in_list_view is not None:
                override_field.in_list_view = upd.in_list_view
            if upd.idx is not None:
                override_field.idx = upd.idx
            if upd.in_filter is not None:
                override_field.in_filter = upd.in_filter
            if upd.in_quick_entry is not None:
                override_field.in_quick_entry = upd.in_quick_entry

        session.commit()


meta_service = MetaService()
