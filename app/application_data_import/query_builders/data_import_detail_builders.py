# app/application_data_import/query_builders/data_import_detail_builders.py
from __future__ import annotations

from typing import Dict, Any, Optional, List

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.security.rbac_effective import AffiliationContext
from app.application_data_import.models import (
    DataImport,
    DataImportTemplateField,
    DataImportLog,
    ImportStatus,
)
from app.application_org.models.company import Company, Branch


def _enum_value(x) -> Optional[str]:
    if x is None:
        return None
    return getattr(x, "value", x)


def _has_platform_admin_scope(ctx: AffiliationContext) -> bool:
    if getattr(ctx, "is_system_admin", False):
        return True
    roles = getattr(ctx, "roles", []) or []
    roles_l = {str(r).strip().lower() for r in roles if r}
    return "system admin" in roles_l or "super admin" in roles_l


def _get_company_scope(ctx: AffiliationContext) -> Optional[int]:
    return getattr(ctx, "company_id", None)


def resolve_data_import_by_code(
    s: Session, ctx: AffiliationContext, code: str
) -> int:
    DI = DataImport

    if _has_platform_admin_scope(ctx):
        stmt = select(DI.id).where(DI.code == code)
    else:
        company_id = _get_company_scope(ctx)
        if not company_id:
            raise NotFound("Data Import not found.")
        stmt = select(DI.id).where(DI.code == code, DI.company_id == company_id)

    row = s.execute(stmt).first()
    if not row:
        raise NotFound("Data Import not found.")

    return int(row[0])


def load_data_import_detail(
    s: Session,
    ctx: AffiliationContext,
    data_import_id: int,
) -> Dict[str, Any]:
    DI = DataImport
    C = Company
    B = Branch

    if _has_platform_admin_scope(ctx):
        stmt = (
            select(
                DI.id,
                DI.code,
                DI.reference_doctype,
                DI.import_type,
                DI.file_type,
                DI.status,
                DI.company_id,
                DI.branch_id,
                DI.created_by_id,
                DI.import_file_key,
                DI.google_sheets_url,
                DI.total_rows,
                DI.successful_rows,
                DI.failed_rows,
                DI.mute_emails,
                DI.job_id,
                DI.payload,
                DI.created_at,
                DI.updated_at,
                C.name.label("company_name"),
                B.name.label("branch_name"),
            )
            .select_from(DI)
            .join(C, C.id == DI.company_id)
            .outerjoin(B, B.id == DI.branch_id)
            .where(DI.id == data_import_id)
        )
    else:
        company_id = _get_company_scope(ctx)
        if not company_id:
            raise NotFound("Data Import not found.")

        stmt = (
            select(
                DI.id,
                DI.code,
                DI.reference_doctype,
                DI.import_type,
                DI.file_type,
                DI.status,
                DI.company_id,
                DI.branch_id,
                DI.created_by_id,
                DI.import_file_key,
                DI.google_sheets_url,
                DI.total_rows,
                DI.successful_rows,
                DI.failed_rows,
                DI.mute_emails,
                DI.job_id,
                DI.payload,
                DI.created_at,
                DI.updated_at,
                C.name.label("company_name"),
                B.name.label("branch_name"),
            )
            .select_from(DI)
            .join(C, C.id == DI.company_id)
            .outerjoin(B, B.id == DI.branch_id)
            .where(DI.id == data_import_id)
            .where(DI.company_id == company_id)
        )

    row = s.execute(stmt).mappings().first()
    if not row:
        raise NotFound("Data Import not found.")

    status_enum = row["status"]
    import_file_key = row.get("import_file_key")
    has_file = bool(import_file_key)

    can_start = status_enum == ImportStatus.NOT_STARTED and has_file
    can_retry = status_enum in (ImportStatus.FAILED, ImportStatus.PARTIAL_SUCCESS) and has_file

    TF = DataImportTemplateField
    tf_stmt = (
        select(
            TF.id,
            TF.field_name,
            TF.field_label,
            TF.column_index,
            TF.is_required,
        )
        .where(TF.data_import_id == data_import_id)
        .order_by(TF.column_index.asc())
    )
    tf_rows = s.execute(tf_stmt).mappings().all()

    template_fields: List[Dict[str, Any]] = [
        {
            "id": r["id"],
            "field_name": r["field_name"],
            "field_label": r["field_label"],
            "column_index": r["column_index"],
            "is_required": bool(r["is_required"]),
        }
        for r in tf_rows
    ]

    LOG = DataImportLog
    log_stmt = (
        select(
            LOG.id,
            LOG.row_index,
            LOG.success,
            LOG.messages,
        )
        .where(LOG.data_import_id == data_import_id)
        .order_by(LOG.row_index.asc())
    )
    log_rows = s.execute(log_stmt).mappings().all()

    logs: List[Dict[str, Any]] = [
        {
            "id": r["id"],
            "row_index": r["row_index"],
            "success": bool(r["success"]),
            "messages": r["messages"] or [],
        }
        for r in log_rows
    ]

    di = {
        "id": row["id"],
        "code": row["code"],
        "reference_doctype": row["reference_doctype"],
        "import_type": _enum_value(row["import_type"]),
        "file_type": _enum_value(row["file_type"]),
        "status": _enum_value(status_enum),
        "company": {
            "id": row["company_id"],
            "name": row["company_name"],
        },
        "branch": (
            {
                "id": row["branch_id"],
                "name": row["branch_name"],
            }
            if row.get("branch_id")
            else None
        ),
        "file": {
            "import_file_key": import_file_key,
            "google_sheets_url": row.get("google_sheets_url"),
        },
        "stats": {
            "total_rows": row["total_rows"],
            "successful_rows": row["successful_rows"],
            "failed_rows": row["failed_rows"],
        },
        "job": {
            "job_id": row.get("job_id"),
        },
        "options": {
            "mute_emails": bool(row["mute_emails"]),
        },
        "payload": row.get("payload") or {},
        "actions": {
            "can_start": can_start,
            "can_retry": can_retry,
        },
    }

    return {
        "data_import": di,
        "template_fields": template_fields,
        "logs": logs,
        "meta": {
            "created_at": row["created_at"].isoformat()
            if row.get("created_at")
            else None,
            "updated_at": row["updated_at"].isoformat()
            if row.get("updated_at")
            else None,
        },
    }
