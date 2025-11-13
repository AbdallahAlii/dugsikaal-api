# application_data_import/services/import_service.py
from __future__ import annotations
from typing import Optional, Tuple, List, Iterable
from werkzeug.exceptions import NotFound, BadRequest

from config.database import db
from ..models import (
    DataImport, ImportType, FileType, ImportStatus, DataImportLog, DataImportTemplateField
)
from ..storage.files import save_import_file_encrypted
from ..runner.jobs import enqueue_import_job
from ..exporters.error_rows_exporter import export_errors_as
from ..utils.status import set_status
from ..registry.doctype_registry import get_doctype_cfg
from ..registry.field_resolver import resolve_headers_to_fields


def create_data_import_record(
    *,
    company_id: int,
    branch_id: Optional[int],
    created_by_id: int,
    reference_doctype: str,
    import_type: ImportType,
    file_type: FileType,
    mute_emails: bool,
) -> DataImport:
    di = DataImport(
        company_id=company_id,
        branch_id=branch_id,
        created_by_id=created_by_id,
        reference_doctype=reference_doctype,
        import_type=import_type,
        file_type=file_type,
        mute_emails=mute_emails,
        status=ImportStatus.NOT_STARTED,
    )
    db.session.add(di)
    db.session.flush([di])
    return di


def set_template_fields(data_import_id: int, ordered_labels: Iterable[str]) -> None:
    """
    Users send LABELS they selected in the UI. We resolve each label->fieldname using:
      1) registry.template.labels (primary)
      2) doctype meta labels (fallback)
      3) accept exact fieldnames for power users
    Then we persist both field_label and field_name in the chosen order.
    """
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")

    labels = list(ordered_labels or [])
    if not labels:
        raise BadRequest("No fields provided.")

    # Resolve labels -> fieldnames
    header_to_field, unknown = resolve_headers_to_fields(di.reference_doctype, labels)
    if unknown:
        raise BadRequest(f"Unknown fields/labels: {', '.join(unknown)}")

    # Clear previous
    db.session.query(DataImportTemplateField).filter(
        DataImportTemplateField.data_import_id == data_import_id
    ).delete()

    # Persist in order with both label + fieldname
    for i, lbl in enumerate(labels):
        fieldname = header_to_field[lbl]
        db.session.add(DataImportTemplateField(
            data_import_id=data_import_id,
            field_name=fieldname,
            field_label=lbl,               # keep the exact label the user picked
            column_index=i,
            is_required=False              # visual; true required handled by policy at runtime
        ))
    db.session.flush()


def attach_import_file_encrypted(di: DataImport, file_bytes: bytes, filename: str) -> None:
    key = save_import_file_encrypted(di.id, filename, file_bytes)
    di.import_file_key = key
    db.session.flush([di])


def attach_file_by_id(data_import_id: int, file_bytes: bytes, filename: str) -> None:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")
    attach_import_file_encrypted(di, file_bytes, filename)


def start_import_job(data_import_id: int) -> Optional[str]:
    job = enqueue_import_job(data_import_id)
    return getattr(job, "id", None)


def start_by_id(data_import_id: int) -> Optional[str]:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")
    if not di.import_file_key:
        raise BadRequest("No import file attached.")
    job = enqueue_import_job(data_import_id)
    return getattr(job, "id", None)


def _collect_failed_rows(data_import_id: int) -> Tuple[List[dict], List[str]]:
    q = db.session.query(DataImportLog).filter(
        DataImportLog.data_import_id == data_import_id,
        DataImportLog.success.is_(False),
    ).order_by(DataImportLog.row_index.asc())
    rows = q.all()
    out_rows = []
    headers = ["row_index", "errors"]
    for r in rows:
        out_rows.append({"row_index": r.row_index, "errors": "; ".join(r.messages or [])})
    return out_rows, headers


def export_errored_rows(data_import_id: int, file_type: str = "csv") -> Tuple[bytes, str, str]:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")
    data_rows, headers = _collect_failed_rows(data_import_id)
    content, filename, mimetype = export_errors_as(headers, data_rows, di.reference_doctype, file_type=file_type)
    return content, filename, mimetype


def get_status(data_import_id: int) -> dict:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")
    return {
        "id": di.id,
        "status": di.status.value,
        "total_rows": di.total_rows,
        "successful_rows": di.successful_rows,
        "failed_rows": di.failed_rows,
        "job_id": di.job_id,
    }
