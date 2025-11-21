# # application_data_import/runner/pipeline.py
# from __future__ import annotations
# from typing import Any, Dict, List, Tuple, Optional
#
# from sqlalchemy.exc import IntegrityError
# from werkzeug.exceptions import BadRequest
#
# from config.database import db
# from ..models import DataImport, DataImportLog, ImportStatus, ImportType, FileType
# from ..storage.files import fetch_import_file_bytes_decrypted
# from ..parsers import read_csv_bytes, read_xlsx_bytes
# from ..services.mapping_service import build_header_map, resolve_links_bulk
# from ..validators.schema_validators import (
#     validate_required_headers,
#     validate_row_shapes,
#     validate_conditionals,
# )
# from ..registry.doctype_registry import get_doctype_cfg, import_callable
# from ..services.policy_service import get_policy
# from ..utils.status import set_status
# from ..registry.field_resolver import resolve_headers_to_fields
#
#
# def _parse(di: DataImport) -> Tuple[List[str], List[Dict[str, Any]]]:
#     if not di.import_file_key:
#         raise BadRequest("Import file not attached.")
#     raw = fetch_import_file_bytes_decrypted(di.import_file_key)
#     if di.file_type == FileType.CSV:
#         return read_csv_bytes(raw)
#     else:
#         return read_xlsx_bytes(raw)
#
#
# def _strip_computed_on_insert(policy, row: Dict[str, Any], import_type: ImportType) -> Dict[str, Any]:
#     if import_type == ImportType.INSERT:
#         for f in policy.computed_fields:
#             row.pop(f, None)
#         for f in policy.exclude_on_insert:
#             row.pop(f, None)
#     return row
#
#
# def _inject_context(di: DataImport, row: Dict[str, Any]) -> None:
#     # Always enforce system context fields from DI
#     row["company_id"] = di.company_id
#     if di.branch_id:
#         row["branch_id"] = di.branch_id
#
#
# def _call_handler(
#     reference_doctype: str,
#     import_type: ImportType,
#     identity_field: str,
#     payload: Dict[str, Any],
# ) -> Tuple[bool, Optional[str]]:
#     cfg = get_doctype_cfg(reference_doctype)
#     if import_type == ImportType.INSERT:
#         fn = import_callable(cfg["handlers"]["create"])
#         fn(payload)  # keep adapter signatures simple
#         return True, None
#     else:
#         upd = cfg["handlers"]["update_by"].get(identity_field)
#         if not upd:
#             return False, f"Update by '{identity_field}' not supported."
#         fn = import_callable(upd)
#         fn(payload)
#         return True, None
#
#
# def run_import(data_import_id: int) -> None:
#     di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
#     if not di:
#         return
#
#     policy = get_policy(di.reference_doctype)
#     identity = policy.identity_for_update
#     set_status(di, ImportStatus.IN_PROGRESS)
#     db.session.commit()
#
#     try:
#         # 0) Parse uploaded file
#         headers, raw_rows = _parse(di)
#
#         # 1) headers mapping (labels/fieldnames -> real fieldnames)
#         #    final_cols = list of backend fieldnames to keep, in order.
#         final_cols, unknown_headers = build_header_map(di.reference_doctype, headers)
#         validate_required_headers(di.reference_doctype, di.import_type, final_cols)
#
#         # 1b) Build header->fieldname map so we can convert row keys from labels to fieldnames.
#         header_to_field, _ = resolve_headers_to_fields(di.reference_doctype, headers)
#
#         # 2) shape rows to expected columns, using fieldnames as keys
#         shaped: List[Dict[str, Any]] = []
#         for r in raw_rows:
#             # r keys are incoming headers (labels or fieldnames)
#             mapped_row: Dict[str, Any] = {}
#
#             for hdr, value in r.items():
#                 fname = header_to_field.get(hdr)
#                 if fname:
#                     mapped_row[fname] = value
#
#             # Keep only the final_cols (and ensure they all exist, even if None)
#             shaped.append({c: mapped_row.get(c) for c in final_cols})
#
#         validate_row_shapes(shaped)
#
#         # 3) conditional rules (e.g., base_uom_id required if item_type=Stock)
#         validate_conditionals(di.reference_doctype, shaped)
#
#         # 4) bulk resolve links by name → id (Item Group, UOM, Brand, etc)
#         resolved, link_errors = resolve_links_bulk(di.reference_doctype, shaped, di.company_id)
#
#         # 5) iterate rows → strip computed/excluded; inject context; call domain handler
#         total = len(resolved)
#         ok_count = 0
#         fail_count = 0
#
#         # clear previous logs
#         db.session.query(DataImportLog).filter(
#             DataImportLog.data_import_id == di.id
#         ).delete()
#
#         for i, row in enumerate(resolved):
#             msgs: List[str] = []
#             if any(ei == i for ei, _ in link_errors):
#                 msgs.extend([m for (ei, m) in link_errors if ei == i])
#
#             try:
#                 row = _strip_computed_on_insert(policy, row, di.import_type)
#                 _inject_context(di, row)
#
#                 # For Update: ensure identity present
#                 if di.import_type == ImportType.UPDATE and (row.get(identity) in (None, "")):
#                     raise BadRequest(f"Missing identity field '{identity}' for update.")
#
#                 success, err = _call_handler(di.reference_doctype, di.import_type, identity, row)
#                 if not success and err:
#                     msgs.append(err)
#                     raise BadRequest(err)
#
#                 ok = True
#                 ok_count += 1
#             except Exception as e:
#                 ok = False
#                 fail_count += 1
#                 if isinstance(e, IntegrityError):
#                     msgs.append("Integrity error (duplicate or constraint).")
#                 else:
#                     msgs.append(str(e) or "Failed.")
#                 db.session.rollback()
#             finally:
#                 log = DataImportLog(
#                     data_import_id=di.id,
#                     row_index=i,
#                     success=ok,
#                     messages=msgs or None,
#                 )
#                 db.session.add(log)
#                 db.session.flush([log])
#
#         di.total_rows = total
#         di.successful_rows = ok_count
#         di.failed_rows = fail_count
#
#         if fail_count == 0:
#             set_status(di, ImportStatus.SUCCESS)
#         elif ok_count == 0:
#             set_status(di, ImportStatus.FAILED)
#         else:
#             set_status(di, ImportStatus.PARTIAL_SUCCESS)
#
#         db.session.commit()
#
#     except Exception:
#         db.session.rollback()
#         set_status(di, ImportStatus.FAILED)
#         db.session.commit()
# application_data_import/runner/pipeline.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional
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
    # Always enforce system context fields from DI
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
    cfg = get_doctype_cfg(reference_doctype)
    if import_type == ImportType.INSERT:
        fn = import_callable(cfg["handlers"]["create"])
        logger.debug(
            "_call_handler: calling CREATE handler for doctype=%s payload=%s",
            reference_doctype,
            payload,
        )
        fn(payload)  # keep adapter signatures simple
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


def run_import(data_import_id: int) -> None:
    di: Optional[DataImport] = db.session.get(DataImport, data_import_id)
    if not di:
        logger.error("run_import: DataImport id=%s not found", data_import_id)
        return

    logger.info(
        "run_import[%s]: starting for doctype=%s company_id=%s branch_id=%s import_type=%s file_type=%s",
        di.id,
        di.reference_doctype,
        di.company_id,
        di.branch_id,
        di.import_type.name,
        di.file_type.name,
    )

    policy = get_policy(di.reference_doctype)
    identity = policy.identity_for_update

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

        # 3) conditional rules (e.g., base_uom_id required if item_type=Stock)
        validate_conditionals(di.reference_doctype, shaped)
        logger.info("run_import[%s]: conditional validation passed", di.id)

        # 4) bulk resolve links by name → id (Item Group, UOM, Brand, etc)
        resolved, link_errors = resolve_links_bulk(di.reference_doctype, shaped, di.company_id)
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

        # 5) iterate rows → strip computed/excluded; inject context; call domain handler
        total = len(resolved)
        ok_count = 0
        fail_count = 0

        # clear previous logs
        db.session.query(DataImportLog).filter(
            DataImportLog.data_import_id == di.id
        ).delete()

        for i, row in enumerate(resolved):
            msgs: List[str] = []
            if any(ei == i for ei, _ in link_errors):
                msgs.extend([m for (ei, m) in link_errors if ei == i])

            try:
                logger.debug("run_import[%s]: processing row %d initial=%s", di.id, i, row)
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
                logger.debug("run_import[%s]: row %d succeeded", di.id, i)
            except Exception as e:
                ok = False
                fail_count += 1
                if isinstance(e, IntegrityError):
                    msgs.append("Integrity error (duplicate or constraint).")
                else:
                    msgs.append(str(e) or "Failed.")
                logger.exception(
                    "run_import[%s]: row %d failed: %s",
                    di.id,
                    i,
                    e,
                )
                db.session.rollback()
            finally:
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
        set_status(di, ImportStatus.FAILED)
        db.session.commit()
