from __future__ import annotations

import logging

from flask import Blueprint, request
from pydantic import ValidationError
from werkzeug.exceptions import NotFound

from config.database import db
from app.business_validation.error_handling import format_validation_error
from app.common.api_response import api_error, api_success

from app.application_education.application_quran_memorization.schemas.quran_schemas import (
    MushafSyncRequest,
    QuranGetVerseRequest,
    QuranListChaptersRequest,
    QuranListSurahVersesRequest,
)
from app.application_education.application_quran_memorization.services.quran_query_service import QuranQueryService
from app.application_education.application_quran_memorization.services.quran_sync_service import QuranSyncService

bp = Blueprint("quran", __name__, url_prefix="/api/quran")
log = logging.getLogger(__name__)


@bp.post("/mushafs/sync")
def sync_mushaf():
    try:
        payload = MushafSyncRequest.model_validate(
            request.get_json(silent=True) or {}
        )
        svc = QuranSyncService(db.session)
        res = svc.sync(payload)
        return api_success(
            message="Sync processed.",
            data=res.model_dump(),
            status_code=200,
        )
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except Exception as e:
        log.exception("sync_mushaf: %s", str(e))
        db.session.rollback()
        return api_error("An unexpected error occurred during sync.", status_code=500)


@bp.get("/mushafs/<string:mushaf_code>/verify")
def verify_mushaf(mushaf_code: str):
    try:
        svc = QuranSyncService(db.session)
        res = svc.verify_mushaf(mushaf_code)
        return api_success(
            message="Verification completed.",
            data=res,
            status_code=200,
        )
    except NotFound as e:
        return api_error(e.description, status_code=404)
    except Exception as e:
        log.exception("verify_mushaf: %s", str(e))
        return api_error("Verification failed.", status_code=500)


@bp.get("/chapters")
def list_chapters():
    try:
        payload = QuranListChaptersRequest.model_validate(
            {
                "mushaf_code": request.args.get("mushaf_code") or "madani_hafs_v1",
            }
        )
        svc = QuranQueryService(db.session)
        rows = svc.list_chapters(payload.mushaf_code)
        return api_success(data={"rows": rows})
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except NotFound as e:
        return api_error(e.description, status_code=404)
    except Exception as e:
        log.exception("list_chapters: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.get("/verses/<string:verse_key>")
def get_verse_by_key(verse_key: str):
    try:
        payload = QuranGetVerseRequest.model_validate(
            {
                "mushaf_code": request.args.get("mushaf_code") or "madani_hafs_v1",
                "words": (request.args.get("words", "true").lower() == "true"),
            }
        )
        svc = QuranQueryService(db.session)
        row = svc.get_verse_by_key(
            mushaf_code=payload.mushaf_code,
            verse_key=verse_key,
            words=payload.words,
        )
        return api_success(data={"verse": row})
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except NotFound as e:
        return api_error(e.description, status_code=404)
    except Exception as e:
        log.exception("get_verse_by_key: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)


@bp.get("/chapters/<int:surah_number>/verses")
def list_surah_verses(surah_number: int):
    try:
        payload = QuranListSurahVersesRequest.model_validate(
            {
                "mushaf_code": request.args.get("mushaf_code") or "madani_hafs_v1",
                "page": int(request.args.get("page", 1)),
                "per_page": int(request.args.get("per_page", 50)),
                "words": (request.args.get("words", "true").lower() == "true"),
            }
        )
        svc = QuranQueryService(db.session)
        rows, total = svc.list_surah_verses(
            mushaf_code=payload.mushaf_code,
            surah_number=surah_number,
            page=payload.page,
            per_page=payload.per_page,
            words=payload.words,
        )
        return api_success(
            data={
                "rows": rows,
                "pagination": {
                    "page": payload.page,
                    "per_page": payload.per_page,
                    "total": total,
                },
            }
        )
    except ValidationError as e:
        return api_error(format_validation_error(e), status_code=422)
    except NotFound as e:
        return api_error(e.description, status_code=404)
    except Exception as e:
        log.exception("list_surah_verses: %s", str(e))
        return api_error("An unexpected error occurred.", status_code=500)
