# application_data_import/runner/pipeline.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional

from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest

from config.database import db
from ..models import DataImport, DataImportLog, ImportStatus, ImportType, FileType
from ..storage.files import fetch_import_file_bytes_decrypted
from ..parsers import read_csv_bytes, read_xlsx_bytes
from ..services.mapping_service import build_header_map, resolve_links_bulk
from ..validators.schema_validators import validate_required_headers, validate_row_shapes, validate_conditionals
from ..registry.doctype_registry import get_doctype_cfg, import_callable
from ..services.policy_service import get_policy
from ..utils.status import set_status


def _parse(di: DataImport) -> Tuple[List[str], List[Dict[str, Any]]]:
    if not di.import_file_key:
        raise BadRequest("Import file not attached.")
    raw = fetch_import_file_bytes_decrypted(di.import_file_key)
    if di.file_type == FileType.CSV:
        return read_csv_bytes(raw)
    else:
        return read_xlsx_bytes(raw)


def _strip_computed_on_insert(policy, row: Dict[str, Any], import_type: ImportType) -> Dict[str, Any]:
    if import_type == ImportType.INSERT:
        for f in policy.computed_fields:
            row.pop(f, None)
        for f in policy.exclude_on_insert:
            row.pop(f, None)
    return row


def _inject_context(di: DataImport, row: Dict[str, Any]) -> None:
    # Always enforce system context fields from DI
    row["company_id"] = di.company_id
    if di.branch_id:
        row["branch_id"] = di.branch_id


def _call_handler(reference_doctype: str, import_type: ImportType, identity_field: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    cfg = get_doctype_cfg(reference_doctype)
    if import_type == ImportType.INSERT:
        fn = import_callable(cfg["handlers"]["create"])
        fn(payload)  # keep adapter signatures simple
        return True, None
    else:
        upd = cfg["handlers"]["update_by"].get(identity_field)
        if not upd:
            return False, f"Update by '{identity_field}' not supported."
        fn = import_callable(upd)
        fn(payload)
        return True, None


def run_import(data_import_id: int) -> None:
    di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
    if not di:
        return

    policy = get_policy(di.reference_doctype)
    identity = policy.identity_for_update
    set_status(di, ImportStatus.IN_PROGRESS)
    db.session.commit()

    try:
        headers, rows = _parse(di)

        # 1) headers mapping (labels/fieldnames -> fieldnames)
        final_cols, unknown_headers = build_header_map(di.reference_doctype, headers)
        validate_required_headers(di.reference_doctype, di.import_type, final_cols)

        # 2) shape rows to expected columns
        shaped: List[Dict[str, Any]] = []
        for r in rows:
            shaped.append({c: r.get(c) for c in final_cols})

        validate_row_shapes(shaped)

        # 3) conditional rules (e.g., base_uom_id required if item_type=Stock)
        validate_conditionals(di.reference_doctype, shaped)

        # 4) bulk resolve links by name → id
        resolved, link_errors = resolve_links_bulk(di.reference_doctype, shaped, di.company_id)

        # 5) iterate rows → strip computed/excluded; inject context; call domain
        total = len(resolved)
        ok_count = 0
        fail_count = 0

        # clear previous logs
        db.session.query(DataImportLog).filter(DataImportLog.data_import_id == di.id).delete()

        for i, row in enumerate(resolved):
            msgs: List[str] = []
            if any(ei == i for ei, _ in link_errors):
                msgs.extend([m for (ei, m) in link_errors if ei == i])

            try:
                row = _strip_computed_on_insert(policy, row, di.import_type)
                _inject_context(di, row)

                # For Update: ensure identity present
                if di.import_type == ImportType.UPDATE and (row.get(identity) in (None, "")):
                    raise BadRequest(f"Missing identity field '{identity}' for update.")

                success, err = _call_handler(di.reference_doctype, di.import_type, identity, row)
                if not success and err:
                    msgs.append(err)
                    raise BadRequest(err)

                ok = True
                ok_count += 1
            except Exception as e:
                ok = False
                fail_count += 1
                if isinstance(e, IntegrityError):
                    msgs.append("Integrity error (duplicate or constraint).")
                else:
                    msgs.append(str(e) or "Failed.")
                db.session.rollback()
            finally:
                log = DataImportLog(
                    data_import_id=di.id,
                    row_index=i,
                    success=ok,
                    messages=msgs or None
                )
                db.session.add(log)
                db.session.flush([log])

        di.total_rows = total
        di.successful_rows = ok_count
        di.failed_rows = fail_count

        if fail_count == 0:
            set_status(di, ImportStatus.SUCCESS)
        elif ok_count == 0:
            set_status(di, ImportStatus.FAILED)
        else:
            set_status(di, ImportStatus.PARTIAL_SUCCESS)

        db.session.commit()

    except Exception:
        db.session.rollback()
        set_status(di, ImportStatus.FAILED)
        db.session.commit()
