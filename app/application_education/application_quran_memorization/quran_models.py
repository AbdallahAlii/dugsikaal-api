from __future__ import annotations

import datetime as dt
from sqlalchemy.dialects.postgresql import JSONB

from app.common.models.base import TimestampMixin
from config.database import db



class QuranMushaf(db.Model, TimestampMixin):
    __tablename__ = "quran_mushafs"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False, index=True)

    name = db.Column(db.String(255), nullable=False)
    narration = db.Column(db.String(80), nullable=True)
    language = db.Column(db.String(20), nullable=False, default="ar")

    pages_count = db.Column(db.Integer, nullable=True)
    default_script = db.Column(db.String(50), nullable=True)

    raw_json = db.Column(JSONB, nullable=True)

    surahs = db.relationship("QuranSurah", back_populates="mushaf", lazy="dynamic")
    ayahs = db.relationship("QuranAyah", back_populates="mushaf", lazy="dynamic")
    words = db.relationship("QuranWord", back_populates="mushaf", lazy="dynamic")


class QuranSurah(db.Model, TimestampMixin):
    __tablename__ = "quran_surahs"

    id = db.Column(db.Integer, primary_key=True)

    mushaf_id = db.Column(
        db.Integer,
        db.ForeignKey("quran_mushafs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    surah_number = db.Column(db.Integer, nullable=False)  # 1..114

    revelation_place = db.Column(db.String(20), nullable=True)  # makkah / madinah
    revelation_order = db.Column(db.Integer, nullable=True)
    bismillah_pre = db.Column(db.Boolean, nullable=False, default=True)

    name_simple = db.Column(db.String(255), nullable=False)
    name_complex = db.Column(db.String(255), nullable=True)
    name_arabic = db.Column(db.String(255), nullable=True)

    verses_count = db.Column(db.Integer, nullable=True)

    page_start = db.Column(db.Integer, nullable=True)
    page_end = db.Column(db.Integer, nullable=True)

    translated_name = db.Column(db.String(255), nullable=True)
    translated_language_name = db.Column(db.String(80), nullable=True)

    raw_json = db.Column(JSONB, nullable=True)

    mushaf = db.relationship("QuranMushaf", back_populates="surahs")
    ayahs = db.relationship("QuranAyah", back_populates="surah", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint(
            "mushaf_id",
            "surah_number",
            name="uq_quran_surah_per_mushaf",
        ),
        db.Index(
            "ix_quran_surah_mushaf_surah_number",
            "mushaf_id",
            "surah_number",
        ),
    )


class QuranAyah(db.Model, TimestampMixin):
    __tablename__ = "quran_ayahs"

    id = db.Column(db.Integer, primary_key=True)

    mushaf_id = db.Column(
        db.Integer,
        db.ForeignKey("quran_mushafs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    surah_id = db.Column(
        db.Integer,
        db.ForeignKey("quran_surahs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    surah_number = db.Column(db.Integer, nullable=False)  # 1..114
    ayah_number = db.Column(db.Integer, nullable=False)   # 1..N

    verse_key = db.Column(db.String(20), nullable=False, index=True)  # "2:255"

    # Structural metadata
    global_index = db.Column(db.Integer, nullable=True)
    page_number = db.Column(db.Integer, nullable=True)
    juz_number = db.Column(db.Integer, nullable=True)
    hizb_number = db.Column(db.Integer, nullable=True)
    rub_el_hizb_number = db.Column(db.Integer, nullable=True)
    ruku_number = db.Column(db.Integer, nullable=True)
    manzil_number = db.Column(db.Integer, nullable=True)
    sajdah_number = db.Column(db.Integer, nullable=True)

    # Text variants
    text_uthmani = db.Column(db.Text, nullable=True)
    text_uthmani_simple = db.Column(db.Text, nullable=True)
    text_imlaei = db.Column(db.Text, nullable=True)
    text_imlaei_simple = db.Column(db.Text, nullable=True)
    text_indopak = db.Column(db.Text, nullable=True)
    text_qpc_hafs = db.Column(db.Text, nullable=True)
    text_qpc_nastaleeq = db.Column(db.Text, nullable=True)
    text_uthmani_tajweed = db.Column(db.Text, nullable=True)

    raw_json = db.Column(JSONB, nullable=True)

    mushaf = db.relationship("QuranMushaf", back_populates="ayahs")
    surah = db.relationship("QuranSurah", back_populates="ayahs")
    words = db.relationship("QuranWord", back_populates="ayah", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint(
            "mushaf_id",
            "verse_key",
            name="uq_quran_ayah_key_per_mushaf",
        ),
        db.Index(
            "ix_quran_ayah_mushaf_surah_ayah",
            "mushaf_id",
            "surah_number",
            "ayah_number",
        ),
    )


class QuranWord(db.Model, TimestampMixin):
    __tablename__ = "quran_words"

    id = db.Column(db.Integer, primary_key=True)

    mushaf_id = db.Column(
        db.Integer,
        db.ForeignKey("quran_mushafs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ayah_id = db.Column(
        db.Integer,
        db.ForeignKey("quran_ayahs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    position = db.Column(db.Integer, nullable=False)  # 1..N within ayah

    char_type_name = db.Column(db.String(50), nullable=True)
    text = db.Column(db.Text, nullable=True)
    code_v1 = db.Column(db.String(50), nullable=True)
    code_v2 = db.Column(db.String(50), nullable=True)

    page_number = db.Column(db.Integer, nullable=True)
    line_number = db.Column(db.Integer, nullable=True)
    v1_page = db.Column(db.Integer, nullable=True)
    v2_page = db.Column(db.Integer, nullable=True)

    audio_url = db.Column(db.Text, nullable=True)
    translation = db.Column(db.Text, nullable=True)
    transliteration = db.Column(db.Text, nullable=True)

    raw_json = db.Column(JSONB, nullable=True)

    mushaf = db.relationship("QuranMushaf", back_populates="words")
    ayah = db.relationship("QuranAyah", back_populates="words")

    __table_args__ = (
        db.UniqueConstraint(
            "mushaf_id",
            "ayah_id",
            "position",
            name="uq_quran_word_pos_per_ayah_mushaf",
        ),
        db.Index(
            "ix_quran_word_ayah_position",
            "ayah_id",
            "position",
        ),
    )
