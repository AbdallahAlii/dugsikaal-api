# application_data_import/api.py
from __future__ import annotations
import io
from typing import Optional, List
from flask import Blueprint, request, g, send_file
from werkzeug.exceptions import BadRequest, NotFound, Forbidden

from config.database import db
from app.common.api_response import api_success, api_error
from app.security.rbac_guards import require_permission
from app.security.rbac_effective import AffiliationContext

from .models import DataImport, ImportType, FileType, ImportStatus
from .schemas.dto import (
    DownloadTemplateInput, StartImportInput, RetryImportInput,
    CreateImportInput, SetTemplateFieldsInput, AttachFileInput, StartByIdInput, SetTemplateFieldsBody
)
from .services.template_service import build_template_file
from .services.import_service import (
    create_data_import_record, attach_import_file_encrypted, attach_file_by_id,
    start_import_job, export_errored_rows, set_template_fields, start_by_id,
    get_status
)
from .utils.status import set_status
from .registry.doctype_registry import get_doctype_cfg
from .queries.logs import list_logs

bp = Blueprint("data_imports", __name__, url_prefix="/api/data-imports")


def _ctx() -> AffiliationContext:
    return g.auth  # your middleware sets this


# ---------- Legacy one-shot template (no import_id) ----------
@bp.post("/download-template")
@require_permission("Data Import", "Read")
def download_template():
    try:
        payload = DownloadTemplateInput.model_validate(request.get_json() or {})
        cfg = get_doctype_cfg(payload.reference_doctype)
        if not cfg.get("import_enabled", False):
            raise Forbidden("Import disabled for this DocType.")

        content, filename, mimetype = build_template_file(
            reference_doctype=payload.reference_doctype,
            file_type=payload.file_type,
            export_type=payload.export_type,
            selected_fields=payload.selected_fields or None,
            company_id=_ctx().company_id,
        )
        return send_file(io.BytesIO(content), as_attachment=True, download_name=filename, mimetype=mimetype, max_age=0)
    except Forbidden as e:
        return api_error(str(e), status_code=403)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except BadRequest as e:
        return api_error(str(e), status_code=422)
    except Exception:
        return api_error("Internal server error.", status_code=500)


# ---------- ERPNext-like flow: create -> set fields -> download -> attach -> start ----------

@bp.post("/create")
@require_permission("Data Import", "Create")
def create_import():
    try:
        payload = CreateImportInput.model_validate(request.get_json() or {})
        cfg = get_doctype_cfg(payload.reference_doctype)
        if not cfg.get("import_enabled", False):
            raise Forbidden("Import disabled for this DocType.")
        di = create_data_import_record(
            company_id=_ctx().company_id,
            branch_id=_ctx().branch_id,
            created_by_id=getattr(_ctx(), "user_id", None),
            reference_doctype=payload.reference_doctype,
            import_type=ImportType(payload.import_type),
            file_type=FileType(payload.file_type),
            mute_emails=bool(payload.mute_emails),
        )
        db.session.commit()
        return api_success({"data_import_id": di.id}, "Created", 201)
    except Forbidden as e:
        db.session.rollback()
        return api_error(str(e), status_code=403)
    except Exception:
        db.session.rollback()
        return api_error("Internal server error.", status_code=500)


@bp.post("/<int:data_import_id>/set-template-fields")
@require_permission("Data Import", "Update")
def set_fields(data_import_id: int):
    try:
        di = db.session.get(DataImport, data_import_id)
        if not di:
            raise NotFound("Data Import not found.")

        body = SetTemplateFieldsBody.model_validate(request.get_json() or {})
        # body.fields contains LABELS picked by the user. We will map them to fieldnames.
        set_template_fields(data_import_id, body.fields)  # <-- pass labels, service will map label->fieldname
        db.session.commit()
        return api_success({"data_import_id": data_import_id, "labels": body.fields}, "Saved", 200)
    except NotFound as e:
        db.session.rollback()
        return api_error(str(e), status_code=404)
    except Exception:
        db.session.rollback()
        return api_error("Internal server error.", status_code=500)


@bp.get("/<int:data_import_id>/download-template")
@require_permission("Data Import", "Read")
def download_template_by_id(data_import_id: int):
    try:
        di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
        if not di:
            raise NotFound("Data Import not found.")
        cfg = get_doctype_cfg(di.reference_doctype)
        if not cfg.get("import_enabled", False):
            raise Forbidden("Import disabled for this DocType.")
        content, filename, mimetype = build_template_file(
            reference_doctype=di.reference_doctype,
            file_type=di.file_type,
            export_type="blank",
            selected_fields=None,
            company_id=di.company_id,
            data_import_id=di.id,
        )
        return send_file(io.BytesIO(content), as_attachment=True, download_name=filename, mimetype=mimetype, max_age=0)
    except (NotFound, Forbidden) as e:
        return api_error(str(e), status_code=403 if isinstance(e, Forbidden) else 404)
    except Exception:
        return api_error("Internal server error.", status_code=500)


@bp.post("/<int:data_import_id>/attach-file")
@require_permission("Data Import", "Update")
def attach_file(data_import_id: int):
    try:
        di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
        if not di:
            raise NotFound("Data Import not found.")

        file_storage = request.files.get("file") if request.files else None
        if file_storage:
            attach_import_file_encrypted(di, file_storage.read(), file_storage.filename)
        else:
            # JSON body route
            payload = AttachFileInput.model_validate(request.get_json() or {})
            if payload.data_import_id != data_import_id:
                raise BadRequest("Mismatched data_import_id.")
            attach_file_by_id(data_import_id, payload.file_bytes, payload.filename)

        db.session.commit()
        return api_success({"data_import_id": data_import_id}, "File attached", 200)
    except (NotFound, BadRequest) as e:
        db.session.rollback()
        return api_error(str(e), status_code=404 if isinstance(e, NotFound) else 422)
    except Exception:
        db.session.rollback()
        return api_error("Internal server error.", status_code=500)


@bp.post("/<int:data_import_id>/start")
@require_permission("Data Import", "Create")
def start_by_id_ep(data_import_id: int):
    try:
        job_id = start_by_id(data_import_id)
        di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
        if job_id:
            di.job_id = job_id
            set_status(di, ImportStatus.IN_PROGRESS)
            db.session.commit()
        return api_success({"data_import_id": di.id, "job_id": di.job_id}, "Started", 200)
    except NotFound as e:
        db.session.rollback()
        return api_error(str(e), status_code=404)
    except BadRequest as e:
        db.session.rollback()
        return api_error(str(e), status_code=422)
    except Exception:
        db.session.rollback()
        return api_error("Internal server error.", status_code=500)


@bp.get("/<int:data_import_id>/status")
@require_permission("Data Import", "Read")
def status_ep(data_import_id: int):
    try:
        data = get_status(data_import_id)
        return api_success(data, "OK", 200)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except Exception:
        return api_error("Internal server error.", status_code=500)


@bp.get("/<int:data_import_id>/logs")
@require_permission("Data Import", "Read")
def logs_ep(data_import_id: int):
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 100))
        data = list_logs(data_import_id, page=page, per_page=per_page)
        return api_success(data, "OK", 200)
    except Exception:
        return api_error("Internal server error.", status_code=500)


# ---------- Legacy retry + export-errors (kept) ----------

@bp.post("/retry")
@require_permission("Data Import", "Create")
def retry():
    try:
        payload = RetryImportInput.model_validate(request.get_json() or {})
        di: Optional[DataImport] = db.session.get(DataImport, payload.data_import_id)
        if not di:
            raise NotFound("Data Import not found.")
        job_id = start_import_job(di.id)
        if job_id:
            di.job_id = job_id
            set_status(di, ImportStatus.IN_PROGRESS)
            db.session.commit()
        return api_success({"data_import_id": di.id, "job_id": di.job_id}, "Retry scheduled", 200)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except Exception:
        return api_error("Internal server error.", status_code=500)


@bp.get("/<int:data_import_id>/export-errors")
@require_permission("Data Import", "Read")
def export_errors(data_import_id: int):
    try:
        content, filename, mimetype = export_errored_rows(data_import_id)
        return send_file(io.BytesIO(content), as_attachment=True, download_name=filename, mimetype=mimetype, max_age=0)
    except NotFound as e:
        return api_error(str(e), status_code=404)
    except Exception:
        return api_error("Internal server error.", status_code=500)
