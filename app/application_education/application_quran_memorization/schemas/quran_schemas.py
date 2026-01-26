from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ---------- Sync side ---------- #

Phase = Literal["chapters", "verses", "words"]


class MushafSyncRequest(BaseModel):
    mushaf_code: str = Field(..., examples=["madani_hafs_v1"])
    phases: List[Phase] = Field(
        ...,
        description="Which phases to run: chapters, verses, words",
        examples=[["chapters"], ["verses"], ["words"]],
    )

    language: Optional[str] = Field(
        default="en",
        description="Language for chapter/verse metadata",
    )

    per_page: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Per-page for external verses API",
    )

    limit: int = Field(
        default=200,
        ge=1,
        le=5000,
        description="Max verses/words processed per request",
    )

    include_words: bool = Field(
        default=False,
        description="If true, fetch words when phase=verses; ignored for chapters",
    )

    cursor: Optional[str] = Field(
        default=None,
        description='Opaque cursor "surah=2&page=5" for resumed sync',
    )

    ayah_fields: Optional[Dict[str, bool]] = Field(
        default=None,
        description="Optional fields[...] filter for verses API",
    )
    word_fields: Optional[Dict[str, bool]] = Field(
        default=None,
        description="Optional word_fields[...] filter for verses API",
    )


class MushafSyncProgress(BaseModel):
    surah_number: Optional[int] = None
    page: Optional[int] = None
    per_page: Optional[int] = None


class MushafSyncResponse(BaseModel):
    ok: bool = True
    phase: Optional[str] = None
    mushaf_id: Optional[int] = None
    progress: Optional[MushafSyncProgress] = None
    next_cursor: Optional[str] = None
    done: bool = False
    stats: Optional[Dict[str, Any]] = None


# ---------- Read (UI) side ---------- #


class QuranListChaptersRequest(BaseModel):
    mushaf_code: str = Field("madani_hafs_v1")


class QuranGetVerseRequest(BaseModel):
    mushaf_code: str = Field("madani_hafs_v1")
    words: bool = Field(True)


class QuranListSurahVersesRequest(BaseModel):
    mushaf_code: str = Field("madani_hafs_v1")
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)
    words: bool = Field(True)
