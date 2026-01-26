
# application_data_import/runner/pipeline.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional, Set
import logging

from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest

from config.database import db
from ..models import DataImport, DataImportLog, ImportStatus, ImportType, FileType
from ..storage.files import fetch_import_file_bytes_decrypted
from ..parsers import read_csv_bytes, read_xlsx_bytes
from ..services.mapping_service import build_header_map, resolve_links_bulk
from ..validators.schema_validators import (
    validate_required_headers,
    validate_row_shapes,
    validate_conditionals,
)
from ..registry.doctype_registry import get_doctype_cfg, import_callable
from ..services.policy_service import get_policy
from ..utils.status import set_status
from ..registry.field_resolver import resolve_headers_to_fields

logger = logging.getLogger(__name__)


def _parse(di: DataImport) -> Tuple[List[str], List[Dict[str, Any]]]:
    if not di.import_file_key:
        raise BadRequest("Import file not attached.")

    logger.info(
        "run_import[%s]: fetching attached file key='%s'",
        di.id,
        di.import_file_key,
    )
    raw = fetch_import_file_bytes_decrypted(di.import_file_key)
    logger.info(
        "run_import[%s]: fetched %d bytes (file_type=%s)",
        di.id,
        len(raw),
        di.file_type.name,
    )

    if di.file_type == FileType.CSV:
        headers, rows = read_csv_bytes(raw)
    else:
        headers, rows = read_xlsx_bytes(raw)

    logger.info(
        "run_import[%s]: parsed file -> headers=%s | rows=%d",
        di.id,
        headers,
        len(rows),
    )
    return headers, rows


def _strip_computed_on_insert(policy, row: Dict[str, Any], import_type: ImportType) -> Dict[str, Any]:
    """
    Remove computed and excluded fields for INSERT imports.

    - computed_fields: server-derived fields like 'sku', 'code'
    - exclude_on_insert: fields we never accept from file (id, company_id, etc.)
    """
    if import_type == ImportType.INSERT:
        for f in policy.computed_fields:
            if f in row:
                logger.debug("strip_computed: removing computed field '%s'", f)
            row.pop(f, None)
        for f in policy.exclude_on_insert:
            if f in row:
                logger.debug("strip_computed: removing excluded field '%s'", f)
            row.pop(f, None)
    return row


def _inject_context(di: DataImport, row: Dict[str, Any]) -> None:
    """
    Inject system context fields from DataImport into each row.

    - company_id / branch_id: always enforced from the DataImport
    - created_by_id: who triggered the import
    """
    row["company_id"] = di.company_id
    if di.branch_id:
        row["branch_id"] = di.branch_id

    # Let adapters know which user initiated the import
    if "created_by_id" not in row and getattr(di, "created_by_id", None) is not None:
        row["created_by_id"] = di.created_by_id


def _call_handler(
    reference_doctype: str,
    import_type: ImportType,
    identity_field: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """
    Dispatch into the DocType's configured handler.

    - INSERT → handlers.create
    - UPDATE → handlers.update_by[identity_field]
    """
    cfg = get_doctype_cfg(reference_doctype)
    if import_type == ImportType.INSERT:
        fn = import_callable(cfg["handlers"]["create"])
        logger.debug(
            "_call_handler: calling CREATE handler for doctype=%s payload=%s",
            reference_doctype,
            payload,
        )
        fn(payload)
        return True, None
    else:
        upd = cfg["handlers"]["update_by"].get(identity_field)
        if not upd:
            return False, f"Update by '{identity_field}' not supported."
        fn = import_callable(upd)
        logger.debug(
            "_call_handler: calling UPDATE handler for doctype=%s by '%s' payload=%s",
            reference_doctype,
            identity_field,
            payload,
        )
        fn(payload)
        return True, None


def _normalize_error_message(e: Exception) -> str:
    """
    Convert exceptions to a clean, user-facing message.
    """
    if isinstance(e, BadRequest):
        msg = e.description or str(e)
    elif isinstance(e, IntegrityError):
        msg = "Integrity error (duplicate or constraint)."
    else:
        msg = str(e) or "Failed."

    prefix = "400 Bad Request:"
    if msg.startswith(prefix):
        msg = msg.split(":", 1)[1].strip()

    return msg


def _build_success_message(reference_doctype: str, row: Dict[str, Any]) -> str:
    """
    Build a frappe-style success message like:
        'Successfully imported HSUR0001'
    """
    identifier = (
        row.get("code")
        or row.get("name")
        or row.get("item_code")
        or row.get("item_name")
        or row.get("id")
    )

    if identifier:
        return f"Successfully imported {identifier}"
    return "Successfully imported row"


def run_import(data_import_id: int, only_failed: bool = False) -> None:
    """
    Main import runner.

    - only_failed = False  → normal first run (all rows).
    - only_failed = True   → retry failed rows only (ERP-style 'Retry Failed Rows'):
        * Rows that were previously successful are NOT reprocessed.
        * Logs for failed rows are replaced.
        * Overall stats (successful_rows / failed_rows) reflect final state.
    """
    di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
    if not di:
        logger.error("run_import: DataImport id=%s not found", data_import_id)
        return

    logger.info(
        "run_import[%s]: starting for doctype=%s company_id=%s branch_id=%s import_type=%s file_type=%s only_failed=%s",
        di.id,
        di.reference_doctype,
        di.company_id,
        di.branch_id,
        di.import_type.name,
        di.file_type.name,
        only_failed,
    )

    policy = get_policy(di.reference_doctype)
    identity = policy.identity_for_update

    # Enforce per-DocType policy for auto-submit behavior
    if getattr(di, "submit_after_import", False) and not policy.submit_after_import_allowed:
        # Hard error early instead of half-importing
        raise BadRequest(
            f"Submit after import is not allowed for DocType '{di.reference_doctype}'."
        )

    # ---- Load previous logs if retrying only failed rows ----
    prev_success_idx: Set[int] = set()
    retry_failed_idx: Set[int] = set()

    if only_failed:
        prev_logs: List[DataImportLog] = db.session.query(DataImportLog).filter(
            DataImportLog.data_import_id == di.id
        ).all()
        for log in prev_logs:
            if log.success:
                prev_success_idx.add(log.row_index)
            else:
                retry_failed_idx.add(log.row_index)

        # Delete logs only for failed rows; keep success logs
        if retry_failed_idx:
            db.session.query(DataImportLog).filter(
                DataImportLog.data_import_id == di.id,
                DataImportLog.row_index.in_(list(retry_failed_idx)),
            ).delete(synchronize_session=False)
    else:
        # First/full run: clear all previous logs
        db.session.query(DataImportLog).filter(
            DataImportLog.data_import_id == di.id
        ).delete()

    set_status(di, ImportStatus.IN_PROGRESS)
    db.session.commit()
    logger.info("run_import[%s]: status set to IN_PROGRESS", di.id)

    try:
        # 0) Parse uploaded file
        headers, raw_rows = _parse(di)

        # 1) headers mapping (labels/fieldnames -> real fieldnames)
        final_cols, unknown_headers = build_header_map(di.reference_doctype, headers)
        logger.info(
            "run_import[%s]: final_cols=%s unknown_headers=%s",
            di.id,
            final_cols,
            unknown_headers,
        )

        # 🔹 HARD SAFETY #1: ensure we actually have some valid mapped columns
        if not final_cols:
            raise BadRequest(
                "No valid columns found in the import file. "
                "Please ensure your column headers match the allowed fields "
                "for this document (fieldnames or configured labels)."
            )

        # 🔹 HARD SAFETY #2: unknown headers should fail, not be silently ignored
        if unknown_headers:
            raise BadRequest(
                "Unknown columns in file: " + ", ".join(unknown_headers)
            )

        # Required headers as per model + policy (including template always_include for INSERT)
        validate_required_headers(di.reference_doctype, di.import_type, final_cols)

        # 1b) Build header->fieldname map so we can convert row keys from labels to fieldnames.
        header_to_field, _ = resolve_headers_to_fields(di.reference_doctype, headers)
        logger.debug(
            "run_import[%s]: header_to_field mapping=%s",
            di.id,
            header_to_field,
        )

        # 2) shape rows to expected columns, using fieldnames as keys
        shaped: List[Dict[str, Any]] = []
        for idx, r in enumerate(raw_rows):
            mapped_row: Dict[str, Any] = {}

            for hdr, value in r.items():
                fname = header_to_field.get(hdr)
                if fname:
                    mapped_row[fname] = value

            row_out = {c: mapped_row.get(c) for c in final_cols}
            shaped.append(row_out)

        logger.info(
            "run_import[%s]: built shaped rows count=%d",
            di.id,
            len(shaped),
        )
        validate_row_shapes(shaped)

        # 3) conditional rules
        validate_conditionals(di.reference_doctype, shaped)
        logger.info("run_import[%s]: conditional validation passed", di.id)

        # 4) bulk resolve links by name → id
        resolved, link_errors = resolve_links_bulk(
            di.reference_doctype, shaped, di.company_id
        )
        logger.info(
            "run_import[%s]: after resolve_links_bulk -> rows=%d link_errors=%d",
            di.id,
            len(resolved),
            len(link_errors),
        )
        if link_errors:
            logger.debug(
                "run_import[%s]: link_errors=%s",
                di.id,
                link_errors,
            )

        # 5) iterate rows
        total = len(resolved)
        ok_count = len(prev_success_idx) if only_failed else 0
        fail_count = 0

        for i, row in enumerate(resolved):
            # For retry: process only rows that previously failed
            if only_failed and i not in retry_failed_idx:
                continue

            msgs: List[str] = []

            # link errors collected earlier
            if any(ei == i for ei, _ in link_errors):
                msgs.extend([m for (ei, m) in link_errors if ei == i])

            try:
                logger.debug("run_import[%s]: processing row %d initial=%s", di.id, i, row)
                row = _strip_computed_on_insert(policy, row, di.import_type)
                _inject_context(di, row)

                # Meta flags for handlers/adapters (internal keys)
                # - _submit_after_import: whether to auto-submit (if DocType allows)
                # - _mute_emails: pass email muting preference downstream
                row["_submit_after_import"] = bool(getattr(di, "submit_after_import", False))
                row["_mute_emails"] = bool(getattr(di, "mute_emails", True))

                # For Update: ensure identity present
                if di.import_type == ImportType.UPDATE and (row.get(identity) in (None, "")):
                    raise BadRequest(f"Missing identity field '{identity}' for update.")

                # Row-level transaction (SAVEPOINT)
                with db.session.begin_nested():
                    success, err = _call_handler(
                        di.reference_doctype, di.import_type, identity, row
                    )
                    if not success and err:
                        msgs.append(err)
                        raise BadRequest(err)

                ok = True
                ok_count += 1
                logger.debug("run_import[%s]: row %d succeeded", di.id, i)

                msgs.append(_build_success_message(di.reference_doctype, row))

            except Exception as e:
                ok = False
                fail_count += 1

                clean_msg = _normalize_error_message(e)
                msgs.append(clean_msg)

                logger.exception(
                    "run_import[%s]: row %d failed: %s",
                    di.id,
                    i,
                    e,
                )

            # always log the row we processed (for retry we only log retried ones;
            # previous success logs are kept)
            log = DataImportLog(
                data_import_id=di.id,
                row_index=i,
                success=ok,
                messages=msgs or None,
            )
            db.session.add(log)
            db.session.flush([log])

        di.total_rows = total
        di.successful_rows = ok_count
        di.failed_rows = fail_count

        logger.info(
            "run_import[%s]: finished processing rows total=%d ok=%d failed=%d",
            di.id,
            total,
            ok_count,
            fail_count,
        )

        if fail_count == 0:
            set_status(di, ImportStatus.SUCCESS)
        elif ok_count == 0:
            set_status(di, ImportStatus.FAILED)
        else:
            set_status(di, ImportStatus.PARTIAL_SUCCESS)

        logger.info(
            "run_import[%s]: final status=%s",
            di.id,
            di.status.value,
        )
        db.session.commit()

    except Exception as e:
        logger.exception("run_import[%s]: unhandled exception: %s", di.id, e)
        db.session.rollback()

        try:
            has_logs = db.session.query(DataImportLog.id).filter(
                DataImportLog.data_import_id == di.id
            ).first()
        except Exception:
            has_logs = True

        if not has_logs:
            msg = _normalize_error_message(e)
            log = DataImportLog(
                data_import_id=di.id,
                row_index=-1,
                success=False,
                messages=[msg],
            )
            db.session.add(log)

        set_status(di, ImportStatus.FAILED)
        db.session.commit()
