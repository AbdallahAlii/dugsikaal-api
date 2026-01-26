from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session
from werkzeug.exceptions import NotFound

from app.application_education.application_quran_memorization.repository.quran_repo import QuranRepository


class QuranQueryService:
    def __init__(self, session: Session):
        self.repo = QuranRepository(session)

    def _get_mushaf_id(self, mushaf_code: str) -> int:
        mushaf = self.repo.get_mushaf_by_code(mushaf_code)
        if not mushaf:
            raise NotFound("Mushaf not found. Please run sync first.")
        return mushaf.id

    def list_chapters(self, mushaf_code: str) -> List[Dict[str, Any]]:
        mushaf_id = self._get_mushaf_id(mushaf_code)
        return self.repo.list_chapters_json(mushaf_id)

    def get_verse_by_key(
        self, mushaf_code: str, verse_key: str, words: bool
    ) -> Dict[str, Any]:
        mushaf_id = self._get_mushaf_id(mushaf_code)
        row = self.repo.get_verse_by_key_json(
            mushaf_id=mushaf_id, verse_key=verse_key, include_words=words
        )
        if not row:
            raise NotFound("Verse not found.")
        return row

    def list_surah_verses(
        self,
        mushaf_code: str,
        surah_number: int,
        page: int,
        per_page: int,
        words: bool,
    ) -> Tuple[List[Dict[str, Any]], int]:
        mushaf_id = self._get_mushaf_id(mushaf_code)
        rows, total = self.repo.list_surah_verses_json(
            mushaf_id=mushaf_id,
            surah_number=surah_number,
            page=page,
            per_page=per_page,
            include_words=words,
        )
        return rows, total
