
# application_data_import/services/import_service.py
from __future__ import annotations
import logging
from typing import Optional, Tuple, List, Iterable

from werkzeug.exceptions import NotFound, BadRequest

from config.database import db
from ..models import (
    DataImport,
    ImportType,
    FileType,
    ImportStatus,
    DataImportLog,
    DataImportTemplateField,
)
from ..storage.files import save_import_file_encrypted
from ..runner.jobs import enqueue_import_job
from ..exporters.error_rows_exporter import export_errors_as
from ..utils.status import set_status
from ..registry.doctype_registry import get_doctype_cfg
from ..registry.field_resolver import resolve_headers_to_fields
from app.common.generate_code.service import generate_next_code

logger = logging.getLogger(__name__)


def _generate_data_import_code(company_id: int, branch_id: Optional[int]) -> str:
    PREFIX = "DIMP"
    logger.debug(
        "Generating DataImport code with prefix=%s company_id=%s branch_id=%s",
        PREFIX,
        company_id,
        branch_id,
    )
    code = generate_next_code(prefix=PREFIX, company_id=company_id, branch_id=branch_id)
    logger.debug("Generated DataImport code: %s", code)
    return code


# def create_data_import_record(
#     *,
#     company_id: int,
#     branch_id: Optional[int],
#     created_by_id: int,
#     reference_doctype: str,
#     import_type: ImportType,
#     file_type: FileType,
#     mute_emails: bool,
# ) -> DataImport:
#     logger.info(
#         "Creating DataImport record company_id=%s branch_id=%s user_id=%s "
#         "reference_doctype=%s import_type=%s file_type=%s mute_emails=%s",
#         company_id,
#         branch_id,
#         created_by_id,
#         reference_doctype,
#         import_type,
#         file_type,
#         mute_emails,
#     )
#
#     try:
#         code = _generate_data_import_code(company_id=company_id, branch_id=branch_id)
#
#         di = DataImport(
#             company_id=company_id,
#             branch_id=branch_id,
#             created_by_id=created_by_id,
#             code=code,
#             reference_doctype=reference_doctype,
#             import_type=import_type,
#             file_type=file_type,
#             mute_emails=mute_emails,
#             status=ImportStatus.NOT_STARTED,
#         )
#         db.session.add(di)
#         db.session.flush([di])
#
#         logger.info(
#             "Created DataImport id=%s code=%s reference_doctype=%s",
#             di.id,
#             di.code,
#             di.reference_doctype,
#         )
#         return di
#
#     except Exception:
#         logger.exception(
#             "Failed to create DataImport record "
#             "(company_id=%s branch_id=%s doctype=%s)",
#             company_id,
#             branch_id,
#             reference_doctype,
#         )
#         raise

def create_data_import_record(
    *,
    company_id: int,
    branch_id: Optional[int],
    created_by_id: int,
    reference_doctype: str,
    import_type: ImportType,
    file_type: FileType,
    mute_emails: bool,
    submit_after_import: bool = False,
) -> DataImport:
    """
    Create the DataImport row and assign a human-readable code.

    - submit_after_import is validated against registry policies:
      REGISTRY[doctype]["policies"]["submit_after_import_allowed"].
    """
    logger.info(
        "Creating DataImport record company_id=%s branch_id=%s user_id=%s "
        "reference_doctype=%s import_type=%s file_type=%s mute_emails=%s submit_after_import=%s",
        company_id,
        branch_id,
        created_by_id,
        reference_doctype,
        import_type,
        file_type,
        mute_emails,
        submit_after_import,
    )

    # Validate submit_after_import against registry policy
    cfg = get_doctype_cfg(reference_doctype)
    policies = (cfg.get("policies") or {})
    submit_allowed = bool(policies.get("submit_after_import_allowed", False))

    if submit_after_import and not submit_allowed:
        # ERP-style clear error
        raise BadRequest(
            f"submit_after_import is not allowed for document type '{reference_doctype}'."
        )

    try:
        code = _generate_data_import_code(company_id=company_id, branch_id=branch_id)

        di = DataImport(
            company_id=company_id,
            branch_id=branch_id,
            created_by_id=created_by_id,
            code=code,
            reference_doctype=reference_doctype,
            import_type=import_type,
            file_type=file_type,
            mute_emails=mute_emails,
            submit_after_import=submit_after_import,
            status=ImportStatus.NOT_STARTED,
        )
        db.session.add(di)
        db.session.flush([di])

        logger.info(
            "Created DataImport id=%s code=%s reference_doctype=%s submit_after_import=%s",
            di.id,
            di.code,
            di.reference_doctype,
            di.submit_after_import,
        )
        return di

    except Exception:
        logger.exception(
            "Failed to create DataImport record "
            "(company_id=%s branch_id=%s doctype=%s)",
            company_id,
            branch_id,
            reference_doctype,
        )
        raise
def set_template_fields(data_import_id: int, ordered_labels: Iterable[str]) -> None:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")

    labels = list(ordered_labels or [])
    if not labels:
        raise BadRequest("No fields provided.")

    header_to_field, unknown = resolve_headers_to_fields(di.reference_doctype, labels)
    if unknown:
        raise BadRequest(f"Unknown fields/labels: {', '.join(unknown)}")

    db.session.query(DataImportTemplateField).filter(
        DataImportTemplateField.data_import_id == data_import_id
    ).delete()

    for i, lbl in enumerate(labels):
        fieldname = header_to_field[lbl]
        db.session.add(
            DataImportTemplateField(
                data_import_id=data_import_id,
                field_name=fieldname,
                field_label=lbl,
                column_index=i,
                is_required=False,
            )
        )
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


def start_import_job(data_import_id: int, *, only_failed: bool = False) -> Optional[str]:
    """
    Wrapper around enqueue_import_job so that API can choose:
    - only_failed=False → normal full run
    - only_failed=True  → retry failed rows only
    """
    job = enqueue_import_job(data_import_id, only_failed=only_failed)
    return getattr(job, "id", None)


def start_by_id(data_import_id: int) -> Optional[str]:
    """
    Start an import run for the first time (full file).
    """
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")

    if not di.import_file_key:
        raise BadRequest("No import file attached.")

    if di.status == ImportStatus.IN_PROGRESS:
        raise BadRequest("Import is already in progress.")

    if di.status != ImportStatus.NOT_STARTED:
        raise BadRequest(
            "Only imports in 'Not Started' state can be started. "
            "Use Retry for failed or partial imports."
        )

    job_id = start_import_job(data_import_id, only_failed=False)
    return job_id


def _collect_failed_rows(data_import_id: int) -> Tuple[List[dict], List[str]]:
    q = db.session.query(DataImportLog).filter(
        DataImportLog.data_import_id == data_import_id,
        DataImportLog.success.is_(False),
    ).order_by(DataImportLog.row_index.asc())
    rows = q.all()
    out_rows: List[dict] = []
    headers = ["row_index", "errors"]
    for r in rows:
        out_rows.append(
            {"row_index": r.row_index, "errors": "; ".join(r.messages or [])}
        )
    return out_rows, headers


def export_errored_rows(
    data_import_id: int, file_type: str = "csv"
) -> Tuple[bytes, str, str]:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")
    data_rows, headers = _collect_failed_rows(data_import_id)
    content, filename, mimetype = export_errors_as(
        headers, data_rows, di.reference_doctype, file_type=file_type
    )
    return content, filename, mimetype


def get_status(data_import_id: int) -> dict:
    di = db.session.get(DataImport, data_import_id)
    if not di:
        raise NotFound("Data Import not found.")

    has_file = bool(di.import_file_key)
    can_start = di.status == ImportStatus.NOT_STARTED and has_file
    can_retry = di.status in (ImportStatus.FAILED, ImportStatus.PARTIAL_SUCCESS) and has_file

    return {
        "id": di.id,
        "status": di.status.value,
        "total_rows": di.total_rows,
        "successful_rows": di.successful_rows,
        "failed_rows": di.failed_rows,
        "job_id": di.job_id,
        "can_start": can_start,
        "can_retry": can_retry,
    }
