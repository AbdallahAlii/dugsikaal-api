# app/seed_data/meta_doctypes/seeder.py
from __future__ import annotations
import logging
from typing import Optional, Tuple, Dict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application_meta.models import Doctype, DocField, DocLink
from .data import DOCTYPE_META_SPECS

logger = logging.getLogger(__name__)


def _get_or_create_doctype(
    db: Session,
    *,
    name: str,
    defaults: dict,
) -> Tuple[Doctype, bool]:
    dt = db.scalar(select(Doctype).where(Doctype.name == name))
    if dt:
        return dt, False

    dt = Doctype(name=name, **defaults)
    db.add(dt)
    try:
        db.flush()
        return dt, True
    except IntegrityError:
        db.rollback()
        dt = db.scalar(select(Doctype).where(Doctype.name == name))
        return dt, False


def _get_or_create_field(
    db: Session,
    *,
    doctype_id: int,
    fieldname: str,
    defaults: dict,
) -> Tuple[DocField, bool]:
    f = db.scalar(
        select(DocField).where(
            DocField.doctype_id == doctype_id,
            DocField.fieldname == fieldname,
            DocField.company_id.is_(None),  # base meta only
        )
    )
    if f:
        return f, False

    f = DocField(doctype_id=doctype_id, fieldname=fieldname, **defaults)
    db.add(f)
    try:
        db.flush()
        return f, True
    except IntegrityError:
        db.rollback()
        f = db.scalar(
            select(DocField).where(
                DocField.doctype_id == doctype_id,
                DocField.fieldname == fieldname,
                DocField.company_id.is_(None),
            )
        )
        return f, False


def _get_or_create_link(
    db: Session,
    *,
    parent_doctype: str,
    link_doctype: str,
    link_fieldname: Optional[str],
    group_label: Optional[str],
) -> Tuple[DocLink, bool]:
    q = select(DocLink).where(
        DocLink.parent_doctype == parent_doctype,
        DocLink.link_doctype == link_doctype,
        DocLink.link_fieldname == link_fieldname,
    )
    link = db.scalar(q)
    if link:
        return link, False

    link = DocLink(
        parent_doctype=parent_doctype,
        link_doctype=link_doctype,
        link_fieldname=link_fieldname,
        group_label=group_label,
    )
    db.add(link)
    try:
        db.flush()
        return link, True
    except IntegrityError:
        db.rollback()
        link = db.scalar(q)
        return link, False


def seed_meta_doctypes(db: Session) -> None:
    """
    Idempotent seeding of Doctype + DocField + DocLink meta layer.

    - Creates/updates Doctype rows from DOCTYPE_META_SPECS
    - Creates/updates DocField rows for each configured fieldname (company_id IS NULL)
    - Creates/updates DocLink rows
    """
    logger.info("Seeding meta doctypes (Doctype, DocField, DocLink)...")

    for spec in DOCTYPE_META_SPECS:
        name = spec["name"].strip()
        label = spec.get("label", name).strip()
        module = spec["module"].strip()
        table_name = spec["table_name"].strip()

        defaults = dict(
            label=label,
            module=module,
            table_name=table_name,
            icon=spec.get("icon"),
            is_child=bool(spec.get("is_child", False)),
            is_single=bool(spec.get("is_single", False)),
            is_tree=bool(spec.get("is_tree", False)),
            is_submittable=bool(spec.get("is_submittable", False)),
            track_changes=bool(spec.get("track_changes", True)),
            track_seen=bool(spec.get("track_seen", False)),
            track_views=bool(spec.get("track_views", True)),
            quick_entry=bool(spec.get("quick_entry", False)),
            description=spec.get("description"),
        )

        dt, created = _get_or_create_doctype(db, name=name, defaults=defaults)
        if created:
            logger.info("  + Doctype %s (%s) created", name, module)
        else:
            # update basic attributes if changed
            changed = False
            for key, value in defaults.items():
                if getattr(dt, key) != value:
                    setattr(dt, key, value)
                    changed = True
            if changed:
                logger.info("  ~ Doctype %s updated", name)

        # ---- Fields ----
        fields_specs = spec.get("fields", [])
        for f_spec in fields_specs:
            fieldname = f_spec["fieldname"].strip()
            f_defaults: Dict = dict(
                label=f_spec.get("label"),
                fieldtype=f_spec.get("fieldtype", "Data"),
                options=f_spec.get("options"),
                default=f_spec.get("default"),
                reqd=bool(f_spec.get("reqd", False)),
                read_only=bool(f_spec.get("read_only", False)),
                hidden=bool(f_spec.get("hidden", False)),
                in_list_view=bool(f_spec.get("in_list_view", False)),
                in_filter=bool(f_spec.get("in_filter", False)),
                in_quick_entry=bool(f_spec.get("in_quick_entry", False)),
                idx=int(f_spec.get("idx", 0)),
                description=f_spec.get("description"),
                company_id=None,
            )
            field, f_created = _get_or_create_field(
                db,
                doctype_id=dt.id,
                fieldname=fieldname,
                defaults=f_defaults,
            )
            if f_created:
                logger.info("    + Field %s.%s created", name, fieldname)
            else:
                # update field if config changed
                changed = False
                for key, value in f_defaults.items():
                    if getattr(field, key) != value:
                        setattr(field, key, value)
                        changed = True
                if changed:
                    logger.info("    ~ Field %s.%s updated", name, fieldname)

        # ---- Links ----
        links_specs = spec.get("links", [])
        for l_spec in links_specs:
            link_doctype = l_spec["link_doctype"].strip()
            link_fieldname = l_spec.get("link_fieldname")
            group_label = l_spec.get("group_label")

            link, l_created = _get_or_create_link(
                db,
                parent_doctype=name,
                link_doctype=link_doctype,
                link_fieldname=link_fieldname,
                group_label=group_label,
            )
            if l_created:
                logger.info(
                    "    + Link %s → %s (%s) created",
                    name,
                    link_doctype,
                    group_label or "",
                )

    db.commit()
    logger.info("✅ Meta doctypes seeding complete.")
