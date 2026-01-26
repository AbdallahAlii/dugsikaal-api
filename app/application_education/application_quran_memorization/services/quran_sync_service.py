from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.application_education.application_quran_memorization.client.quran_api_client import QuranApiClient
from app.application_education.application_quran_memorization.quran_models import QuranAyah
from app.application_education.application_quran_memorization.repository.quran_repo import QuranRepository
from app.application_education.application_quran_memorization.schemas.quran_schemas import (
    MushafSyncProgress,
    MushafSyncRequest,
    MushafSyncResponse,
)

log = logging.getLogger(__name__)


def parse_cursor(cursor: Optional[str]) -> Tuple[int, int]:
    if not cursor:
        return 1, 1
    parts = dict(p.split("=", 1) for p in cursor.split("&") if "=" in p)
    surah = int(parts.get("surah", "1"))
    page = int(parts.get("page", "1"))
    return surah, page


def make_cursor(surah: int, page: int) -> str:
    return f"surah={surah}&page={page}"


class QuranSyncService:
    def __init__(self, session: Session):
        self.s = session
        self.repo = QuranRepository(session)
        self.client = QuranApiClient()

    # --------- SYNC MAIN ENTRY ---------- #

    def sync(self, req: MushafSyncRequest) -> MushafSyncResponse:
        # Ensure mushaf exists
        mushaf = self.repo.upsert_mushaf(
            {
                "code": req.mushaf_code,
                "name": req.mushaf_code,
                "language": "ar",
                "raw_json": {"source": "sync"},
            }
        )

        # Limit API fields (performance)
        ayah_fields = req.ayah_fields or {
            "text_uthmani": True,
            "text_uthmani_simple": True,
            "text_imlaei": True,
            "text_imlaei_simple": True,
            "page_number": True,
            "juz_number": True,
            "hizb_number": True,
            "rub_el_hizb_number": True,
            "ruku_number": True,
            "manzil_number": True,
            "sajdah_number": True,
            "verse_key": True,
            "verse_number": True,
        }
        word_fields = req.word_fields or {
            "text": True,
            "code_v1": True,
            "code_v2": True,
            "page_number": True,
            "line_number": True,
            "audio_url": True,
            "translation": True,
            "transliteration": True,
            "char_type_name": True,
            "position": True,
        }

        for phase in req.phases:
            if phase == "chapters":
                self._sync_chapters(mushaf.id, req.language)
                self.s.commit()
                return MushafSyncResponse(
                    phase="chapters",
                    mushaf_id=mushaf.id,
                    done=True,
                    next_cursor=None,
                    stats={"surahs": self.repo.count_surahs(mushaf.id)},
                )

            if phase in {"verses", "words"}:
                include_words = (phase == "words") or bool(req.include_words)
                res = self._sync_verses_chunk(
                    mushaf_id=mushaf.id,
                    language=req.language,
                    per_page=req.per_page,
                    limit=req.limit,
                    cursor=req.cursor,
                    include_words=include_words,
                    ayah_fields=ayah_fields,
                    word_fields=word_fields,
                    write_words=(phase == "words"),
                )
                self.s.commit()
                return res

        return MushafSyncResponse(ok=True, mushaf_id=mushaf.id, done=True)

    # --------- CHAPTERS ---------- #

    def _sync_chapters(self, mushaf_id: int, language: Optional[str]) -> None:
        data = self.client.get_chapters(language=language)
        chapters = data.get("chapters") or []

        rows: List[Dict[str, Any]] = []
        for ch in chapters:
            pages = ch.get("pages") or [None, None]
            translated = ch.get("translated_name") or {}
            rows.append(
                {
                    "mushaf_id": mushaf_id,
                    "surah_number": int(ch["id"]),
                    "revelation_place": ch.get("revelation_place"),
                    "revelation_order": ch.get("revelation_order"),
                    "bismillah_pre": bool(ch.get("bismillah_pre", True)),
                    "name_simple": ch.get("name_simple") or "",
                    "name_complex": ch.get("name_complex"),
                    "name_arabic": ch.get("name_arabic"),
                    "verses_count": int(ch.get("verses_count") or 0),
                    "page_start": pages[0],
                    "page_end": pages[1],
                    "translated_name": translated.get("name"),
                    "translated_language_name": translated.get("language_name"),
                    "raw_json": ch,
                }
            )

        self.repo.upsert_surahs(rows)

    # --------- VERSES (+ optional WORDS) CHUNK ---------- #

    def _sync_verses_chunk(
        self,
        mushaf_id: int,
        language: Optional[str],
        per_page: int,
        limit: int,
        cursor: Optional[str],
        include_words: bool,
        ayah_fields: Dict[str, bool],
        word_fields: Dict[str, bool],
        write_words: bool,
    ) -> MushafSyncResponse:
        surah_map = self.repo.get_surah_map(mushaf_id)
        if len(surah_map) < 114:
            raise RuntimeError("Chapters not synced yet. Run phase=chapters first.")

        surah, page = parse_cursor(cursor)
        processed = 0

        while surah <= 114:
            payload = self.client.get_verses_by_chapter(
                chapter_number=surah,
                language=language,
                page=page,
                per_page=per_page,
                words=include_words,
                fields=ayah_fields,
                word_fields=word_fields if include_words else None,
            )

            verses = payload.get("verses") or []
            if not verses:
                surah += 1
                page = 1
                continue

            ayah_rows: List[Dict[str, Any]] = []
            word_rows: List[Dict[str, Any]] = []
            surah_id = surah_map[surah]

            for v in verses:
                verse_key = v.get("verse_key") or v.get("verseKey")
                verse_number = v.get("verse_number") or v.get("verseNumber")
                if not verse_key or not verse_number:
                    continue

                ayah_rows.append(
                    {
                        "mushaf_id": mushaf_id,
                        "surah_id": surah_id,
                        "surah_number": surah,
                        "ayah_number": int(verse_number),
                        "verse_key": str(verse_key),
                        "global_index": v.get("id") or v.get("verse_id"),
                        "page_number": v.get("page_number"),
                        "juz_number": v.get("juz_number"),
                        "hizb_number": v.get("hizb_number"),
                        "rub_el_hizb_number": v.get("rub_el_hizb_number"),
                        "ruku_number": v.get("ruku_number"),
                        "manzil_number": v.get("manzil_number"),
                        "sajdah_number": v.get("sajdah_number"),
                        "text_uthmani": v.get("text_uthmani"),
                        "text_uthmani_simple": v.get("text_uthmani_simple"),
                        "text_imlaei": v.get("text_imlaei"),
                        "text_imlaei_simple": v.get("text_imlaei_simple"),
                        "text_indopak": v.get("text_indopak"),
                        "text_qpc_hafs": v.get("text_qpc_hafs"),
                        "text_qpc_nastaleeq": v.get("text_qpc_nastaleeq"),
                        "text_uthmani_tajweed": v.get("text_uthmani_tajweed"),
                        "raw_json": v,
                    }
                )

            self.repo.upsert_ayahs(ayah_rows)

            if write_words and include_words:
                keys = [r["verse_key"] for r in ayah_rows]
                ayah_id_rows = self.s.execute(
                    select(QuranAyah.verse_key, QuranAyah.id).where(
                        QuranAyah.mushaf_id == mushaf_id,
                        QuranAyah.verse_key.in_(keys),
                    )
                ).all()
                ayah_id_map = {k: i for k, i in ayah_id_rows}

                for v in verses:
                    verse_key = v.get("verse_key") or v.get("verseKey")
                    ayah_id = ayah_id_map.get(str(verse_key))
                    if not ayah_id:
                        continue
                    words = v.get("words") or []
                    for w in words:
                        word_rows.append(
                            {
                                "mushaf_id": mushaf_id,
                                "ayah_id": ayah_id,
                                "position": int(w.get("position") or 0),
                                "char_type_name": w.get("char_type_name"),
                                "text": w.get("text"),
                                "code_v1": w.get("code_v1"),
                                "code_v2": w.get("code_v2"),
                                "page_number": w.get("page_number"),
                                "line_number": w.get("line_number"),
                                "v1_page": w.get("v1_page"),
                                "v2_page": w.get("v2_page"),
                                "audio_url": w.get("audio_url"),
                                "translation": w.get("translation"),
                                "transliteration": w.get("transliteration"),
                                "raw_json": w,
                            }
                        )

                self.repo.upsert_words(word_rows)

            processed += len(verses)
            if processed >= limit:
                next_cursor = make_cursor(surah, page + 1)
                return MushafSyncResponse(
                    phase="words" if write_words else "verses",
                    mushaf_id=mushaf_id,
                    progress=MushafSyncProgress(
                        surah_number=surah,
                        page=page,
                        per_page=per_page,
                    ),
                    next_cursor=next_cursor,
                    done=False,
                    stats={"processed": processed},
                )

            page += 1

        return MushafSyncResponse(
            phase="words" if write_words else "verses",
            mushaf_id=mushaf_id,
            done=True,
            next_cursor=None,
            stats={"processed": processed},
        )

    # --------- VERIFY WITH DEEP CHECKS ---------- #

    def verify_mushaf(self, mushaf_code: str) -> Dict[str, Any]:
        mushaf = self.repo.get_mushaf_by_code(mushaf_code)
        if not mushaf:
            raise NotFound("Mushaf not found. Run sync (phase=chapters) first.")

        mushaf_id = mushaf.id

        surahs = self.repo.count_surahs(mushaf_id)
        expected_ayahs = self.repo.expected_ayahs_from_surahs(mushaf_id)
        ayahs = self.repo.count_ayahs(mushaf_id)
        words = self.repo.count_words(mushaf_id)

        wrong_counts = self.repo.find_surahs_with_wrong_ayah_count(mushaf_id)
        missing_ayahs = self.repo.find_missing_ayah_numbers(mushaf_id)
        duplicate_words = self.repo.find_duplicate_word_positions(mushaf_id)

        ok_surahs = surahs == 114
        ok_ayahs = expected_ayahs > 0 and ayahs == expected_ayahs
        no_dup_words = len(duplicate_words) == 0

        return {
            "mushaf_id": mushaf_id,
            "mushaf_code": mushaf.code,
            "counts": {
                "surahs": surahs,
                "ayahs": ayahs,
                "expected_ayahs": expected_ayahs,
                "words": words,
            },
            "checks": {
                "surahs_ok": ok_surahs,
                "ayahs_ok": ok_ayahs,
                "words_present": words > 0,
                "word_positions_unique": no_dup_words,
            },
            "issues": {
                "surahs_with_wrong_ayah_count": wrong_counts,
                "missing_ayah_numbers": missing_ayahs,
                "duplicate_word_positions": duplicate_words,
            },
            "ok": bool(ok_surahs and ok_ayahs and no_dup_words),
        }
