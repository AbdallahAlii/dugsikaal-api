from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.orm import Session

from app.application_education.application_quran_memorization.quran_models import (
    QuranAyah,
    QuranMushaf,
    QuranSurah,
    QuranWord,
)

_JSONB_EMPTY_ARRAY = func.cast("[]", JSONB)


class QuranRepository:
    def __init__(self, session: Session):
        self.s = session

    # ------------- Mushaf ------------- #

    def get_mushaf_by_code(self, code: str) -> Optional[QuranMushaf]:
        return self.s.scalar(select(QuranMushaf).where(QuranMushaf.code == code))

    def upsert_mushaf(self, values: Dict[str, Any]) -> QuranMushaf:
        stmt = pg_insert(QuranMushaf).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[QuranMushaf.code],
            set_={
                "name": stmt.excluded.name,
                "narration": stmt.excluded.narration,
                "language": stmt.excluded.language,
                "pages_count": stmt.excluded.pages_count,
                "default_script": stmt.excluded.default_script,
                "raw_json": stmt.excluded.raw_json,
            },
        ).returning(QuranMushaf.id)

        mushaf_id = self.s.execute(stmt).scalar_one()
        return self.s.get(QuranMushaf, mushaf_id)

    # ------------- Surahs ------------- #

    def upsert_surahs(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(QuranSurah).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_quran_surah_per_mushaf",
            set_={
                "revelation_place": stmt.excluded.revelation_place,
                "revelation_order": stmt.excluded.revelation_order,
                "bismillah_pre": stmt.excluded.bismillah_pre,
                "name_simple": stmt.excluded.name_simple,
                "name_complex": stmt.excluded.name_complex,
                "name_arabic": stmt.excluded.name_arabic,
                "verses_count": stmt.excluded.verses_count,
                "page_start": stmt.excluded.page_start,
                "page_end": stmt.excluded.page_end,
                "translated_name": stmt.excluded.translated_name,
                "translated_language_name": stmt.excluded.translated_language_name,
                "raw_json": stmt.excluded.raw_json,
            },
        )
        self.s.execute(stmt)

    def get_surah_map(self, mushaf_id: int) -> Dict[int, int]:
        rows = self.s.execute(
            select(QuranSurah.surah_number, QuranSurah.id).where(
                QuranSurah.mushaf_id == mushaf_id
            )
        ).all()
        return {int(n): int(i) for n, i in rows}

    # ------------- Ayahs ------------- #

    def upsert_ayahs(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(QuranAyah).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_quran_ayah_key_per_mushaf",
            set_={
                "surah_id": stmt.excluded.surah_id,
                "surah_number": stmt.excluded.surah_number,
                "ayah_number": stmt.excluded.ayah_number,
                "global_index": stmt.excluded.global_index,
                "page_number": stmt.excluded.page_number,
                "juz_number": stmt.excluded.juz_number,
                "hizb_number": stmt.excluded.hizb_number,
                "rub_el_hizb_number": stmt.excluded.rub_el_hizb_number,
                "ruku_number": stmt.excluded.ruku_number,
                "manzil_number": stmt.excluded.manzil_number,
                "sajdah_number": stmt.excluded.sajdah_number,
                "text_uthmani": stmt.excluded.text_uthmani,
                "text_uthmani_simple": stmt.excluded.text_uthmani_simple,
                "text_imlaei": stmt.excluded.text_imlaei,
                "text_imlaei_simple": stmt.excluded.text_imlaei_simple,
                "text_indopak": stmt.excluded.text_indopak,
                "text_qpc_hafs": stmt.excluded.text_qpc_hafs,
                "text_qpc_nastaleeq": stmt.excluded.text_qpc_nastaleeq,
                "text_uthmani_tajweed": stmt.excluded.text_uthmani_tajweed,
                "raw_json": stmt.excluded.raw_json,
            },
        )
        self.s.execute(stmt)

    # ------------- Words ------------- #

    def upsert_words(self, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(QuranWord).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_quran_word_pos_per_ayah_mushaf",
            set_={
                "char_type_name": stmt.excluded.char_type_name,
                "text": stmt.excluded.text,
                "code_v1": stmt.excluded.code_v1,
                "code_v2": stmt.excluded.code_v2,
                "page_number": stmt.excluded.page_number,
                "line_number": stmt.excluded.line_number,
                "v1_page": stmt.excluded.v1_page,
                "v2_page": stmt.excluded.v2_page,
                "audio_url": stmt.excluded.audio_url,
                "translation": stmt.excluded.translation,
                "transliteration": stmt.excluded.transliteration,
                "raw_json": stmt.excluded.raw_json,
            },
        )
        self.s.execute(stmt)

    # ------------- Counts ------------- #

    def count_surahs(self, mushaf_id: int) -> int:
        return int(
            self.s.scalar(
                select(func.count(QuranSurah.id)).where(
                    QuranSurah.mushaf_id == mushaf_id
                )
            )
            or 0
        )

    def count_ayahs(self, mushaf_id: int) -> int:
        return int(
            self.s.scalar(
                select(func.count(QuranAyah.id)).where(
                    QuranAyah.mushaf_id == mushaf_id
                )
            )
            or 0
        )

    def count_words(self, mushaf_id: int) -> int:
        return int(
            self.s.scalar(
                select(func.count(QuranWord.id)).where(
                    QuranWord.mushaf_id == mushaf_id
                )
            )
            or 0
        )

    def expected_ayahs_from_surahs(self, mushaf_id: int) -> int:
        return int(
            self.s.scalar(
                select(func.coalesce(func.sum(QuranSurah.verses_count), 0)).where(
                    QuranSurah.mushaf_id == mushaf_id
                )
            )
            or 0
        )

    # ------------- Deep verification helpers ------------- #

    def find_surahs_with_wrong_ayah_count(
        self, mushaf_id: int
    ) -> List[Dict[str, Any]]:
        """
        Surahs where stored ayah count != verses_count metadata.
        """
        q = (
            select(
                QuranSurah.surah_number,
                QuranSurah.verses_count.label("expected"),
                func.count(QuranAyah.id).label("actual"),
            )
            .outerjoin(
                QuranAyah,
                and_(
                    QuranAyah.mushaf_id == QuranSurah.mushaf_id,
                    QuranAyah.surah_number == QuranSurah.surah_number,
                ),
            )
            .where(QuranSurah.mushaf_id == mushaf_id)
            .group_by(QuranSurah.surah_number, QuranSurah.verses_count)
            .having(
                (QuranSurah.verses_count.isnot(None))
                & (func.count(QuranAyah.id) != QuranSurah.verses_count)
            )
        )

        rows = self.s.execute(q).all()
        return [
            {
                "surah_number": int(surah_number),
                "expected": int(expected) if expected is not None else None,
                "actual": int(actual),
            }
            for surah_number, expected, actual in rows
        ]

    def find_missing_ayah_numbers(self, mushaf_id: int) -> Dict[int, List[int]]:
        """
        For each surah, list missing ayah_numbers compared to verses_count.
        """
        result: Dict[int, List[int]] = {}

        surahs = self.s.execute(
            select(QuranSurah.surah_number, QuranSurah.verses_count).where(
                QuranSurah.mushaf_id == mushaf_id
            )
        ).all()

        for surah_number, verses_count in surahs:
            if not verses_count:
                continue

            ayah_numbers = self.s.execute(
                select(QuranAyah.ayah_number).where(
                    QuranAyah.mushaf_id == mushaf_id,
                    QuranAyah.surah_number == surah_number,
                )
            ).scalars().all()

            existing = {int(n) for n in ayah_numbers if n is not None}
            expected_range = range(1, int(verses_count) + 1)
            missing = [n for n in expected_range if n not in existing]
            if missing:
                result[int(surah_number)] = missing

        return result

    def find_duplicate_word_positions(
        self, mushaf_id: int
    ) -> List[Dict[str, Any]]:
        """
        Duplicate (ayah_id, position) word rows (should not happen with constraint, but acts as sanity check).
        """
        q = (
            select(
                QuranWord.ayah_id,
                QuranWord.position,
                func.count(QuranWord.id).label("count"),
            )
            .where(QuranWord.mushaf_id == mushaf_id)
            .group_by(QuranWord.ayah_id, QuranWord.position)
            .having(func.count(QuranWord.id) > 1)
        )

        rows = self.s.execute(q).all()
        return [
            {
                "ayah_id": int(ayah_id),
                "position": int(position),
                "count": int(count),
            }
            for ayah_id, position, count in rows
        ]

    # ------------- JSON read helpers (for UI, Tarteel-style) ------------- #

    def list_chapters_json(self, mushaf_id: int) -> List[Dict[str, Any]]:
        q = (
            select(
                func.jsonb_build_object(
                    "surah_number",
                    QuranSurah.surah_number,
                    "revelation_place",
                    QuranSurah.revelation_place,
                    "revelation_order",
                    QuranSurah.revelation_order,
                    "bismillah_pre",
                    QuranSurah.bismillah_pre,
                    "name_simple",
                    QuranSurah.name_simple,
                    "name_complex",
                    QuranSurah.name_complex,
                    "name_arabic",
                    QuranSurah.name_arabic,
                    "verses_count",
                    QuranSurah.verses_count,
                    "page_start",
                    QuranSurah.page_start,
                    "page_end",
                    QuranSurah.page_end,
                    "translated_name",
                    QuranSurah.translated_name,
                    "translated_language_name",
                    QuranSurah.translated_language_name,
                ).label("chapter")
            )
            .where(QuranSurah.mushaf_id == mushaf_id)
            .order_by(QuranSurah.surah_number.asc())
        )

        rows = self.s.execute(q).scalars().all()
        return list(rows)

    def get_verse_by_key_json(
        self,
        mushaf_id: int,
        verse_key: str,
        include_words: bool = True,
    ) -> Optional[Dict[str, Any]]:
        words_subq = (
            select(
                func.coalesce(
                    func.jsonb_agg(
                        func.jsonb_build_object(
                            "position",
                            QuranWord.position,
                            "char_type_name",
                            QuranWord.char_type_name,
                            "text",
                            QuranWord.text,
                            "code_v1",
                            QuranWord.code_v1,
                            "code_v2",
                            QuranWord.code_v2,
                            "page_number",
                            QuranWord.page_number,
                            "line_number",
                            QuranWord.line_number,
                            "v1_page",
                            QuranWord.v1_page,
                            "v2_page",
                            QuranWord.v2_page,
                            "audio_url",
                            QuranWord.audio_url,
                            "translation",
                            QuranWord.translation,
                            "transliteration",
                            QuranWord.transliteration,
                        )
                    ).order_by(QuranWord.position.asc()),
                    _JSONB_EMPTY_ARRAY,
                )
            )
            .where(QuranWord.ayah_id == QuranAyah.id)
            .correlate(QuranAyah)
            .scalar_subquery()
        )

        verse_json = func.jsonb_build_object(
            "id",
            QuranAyah.id,
            "verse_key",
            QuranAyah.verse_key,
            "surah_number",
            QuranAyah.surah_number,
            "ayah_number",
            QuranAyah.ayah_number,
            "global_index",
            QuranAyah.global_index,
            "page_number",
            QuranAyah.page_number,
            "juz_number",
            QuranAyah.juz_number,
            "hizb_number",
            QuranAyah.hizb_number,
            "rub_el_hizb_number",
            QuranAyah.rub_el_hizb_number,
            "ruku_number",
            QuranAyah.ruku_number,
            "manzil_number",
            QuranAyah.manzil_number,
            "sajdah_number",
            QuranAyah.sajdah_number,
            "text_uthmani",
            QuranAyah.text_uthmani,
            "text_uthmani_simple",
            QuranAyah.text_uthmani_simple,
            "text_imlaei",
            QuranAyah.text_imlaei,
            "text_imlaei_simple",
            QuranAyah.text_imlaei_simple,
            "text_indopak",
            QuranAyah.text_indopak,
            "text_qpc_hafs",
            QuranAyah.text_qpc_hafs,
            "text_qpc_nastaleeq",
            QuranAyah.text_qpc_nastaleeq,
            "text_uthmani_tajweed",
            QuranAyah.text_uthmani_tajweed,
            "words",
            words_subq if include_words else _JSONB_EMPTY_ARRAY,
        ).label("verse")

        q = (
            select(verse_json)
            .where(
                QuranAyah.mushaf_id == mushaf_id,
                QuranAyah.verse_key == verse_key,
            )
            .limit(1)
        )

        return self.s.execute(q).scalar_one_or_none()

    def list_surah_verses_json(
        self,
        mushaf_id: int,
        surah_number: int,
        page: int = 1,
        per_page: int = 50,
        include_words: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int]:
        total = int(
            self.s.scalar(
                select(func.count(QuranAyah.id)).where(
                    QuranAyah.mushaf_id == mushaf_id,
                    QuranAyah.surah_number == surah_number,
                )
            )
            or 0
        )

        offset = max(page - 1, 0) * per_page

        words_subq = (
            select(
                func.coalesce(
                    func.jsonb_agg(
                        func.jsonb_build_object(
                            "position",
                            QuranWord.position,
                            "char_type_name",
                            QuranWord.char_type_name,
                            "text",
                            QuranWord.text,
                            "code_v1",
                            QuranWord.code_v1,
                            "code_v2",
                            QuranWord.code_v2,
                            "page_number",
                            QuranWord.page_number,
                            "line_number",
                            QuranWord.line_number,
                            "v1_page",
                            QuranWord.v1_page,
                            "v2_page",
                            QuranWord.v2_page,
                            "audio_url",
                            QuranWord.audio_url,
                            "translation",
                            QuranWord.translation,
                            "transliteration",
                            QuranWord.transliteration,
                        )
                    ).order_by(QuranWord.position.asc()),
                    _JSONB_EMPTY_ARRAY,
                )
            )
            .where(QuranWord.ayah_id == QuranAyah.id)
            .correlate(QuranAyah)
            .scalar_subquery()
        )

        verse_json = func.jsonb_build_object(
            "id",
            QuranAyah.id,
            "verse_key",
            QuranAyah.verse_key,
            "surah_number",
            QuranAyah.surah_number,
            "ayah_number",
            QuranAyah.ayah_number,
            "page_number",
            QuranAyah.page_number,
            "juz_number",
            QuranAyah.juz_number,
            "text_uthmani",
            QuranAyah.text_uthmani,
            "text_uthmani_simple",
            QuranAyah.text_uthmani_simple,
            "text_imlaei",
            QuranAyah.text_imlaei,
            "text_imlaei_simple",
            QuranAyah.text_imlaei_simple,
            "words",
            words_subq if include_words else _JSONB_EMPTY_ARRAY,
        ).label("verse")

        q = (
            select(verse_json)
            .where(
                QuranAyah.mushaf_id == mushaf_id,
                QuranAyah.surah_number == surah_number,
            )
            .order_by(QuranAyah.ayah_number.asc())
            .limit(per_page)
            .offset(offset)
        )

        rows = self.s.execute(q).scalars().all()
        return list(rows), total
