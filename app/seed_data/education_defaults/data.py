# app/seed_data/education_defaults/data.py
from __future__ import annotations

from datetime import time
from typing import List, Dict, Any

# ------------------------------------------------------------
# Academic Year policy (ERP-like, clean + predictable)
# ------------------------------------------------------------
# School year starts Aug 1 and ends Jul 31.
ACADEMIC_YEAR_START_MONTH = 8
ACADEMIC_YEAR_START_DAY = 1

# Term windows inside the academic year:
# Term One: Aug 1 -> Dec 31 (start year)
# Term Two: Jan 1 -> Jul 31 (end year)
TERM_ONE_LABEL = "Term One"
TERM_TWO_LABEL = "Term Two"

# ------------------------------------------------------------
# Programs (K12)
# ------------------------------------------------------------
DEFAULT_K12_PROGRAMS: List[Dict[str, Any]] = [
    {"name": f"Grade {i}", "program_type": "K12", "is_enabled": True}
    for i in range(1, 13)
]

# ------------------------------------------------------------
# Courses (Core)
# ------------------------------------------------------------
DEFAULT_COURSES: List[Dict[str, Any]] = [
    {"name": "Arabic",           "course_type": "CORE", "is_enabled": True},
    {"name": "Tarbiyo",          "course_type": "CORE", "is_enabled": True},
    {"name": "Soomaali",         "course_type": "CORE", "is_enabled": True},
    {"name": "English",          "course_type": "CORE", "is_enabled": True},
    {"name": "Cilmiga Bulshada", "course_type": "CORE", "is_enabled": True},
    {"name": "Xisaab",           "course_type": "CORE", "is_enabled": True},
    {"name": "Seynis",           "course_type": "CORE", "is_enabled": True},
    {"name": "Teknoolojiga",     "course_type": "CORE", "is_enabled": True},
    {"name": "Jugraafi",         "course_type": "CORE", "is_enabled": True},
    {"name": "Taariikh",         "course_type": "CORE", "is_enabled": True},
    {"name": "Biology",          "course_type": "CORE", "is_enabled": True},
    {"name": "Chemistry",        "course_type": "CORE", "is_enabled": True},
    {"name": "Physics",          "course_type": "CORE", "is_enabled": True},
    {"name": "Business",         "course_type": "CORE", "is_enabled": True},
]

# ------------------------------------------------------------
# Student Categories (per company)
# ------------------------------------------------------------
DEFAULT_STUDENT_CATEGORIES: List[Dict[str, Any]] = [
    {"name": "Scholarship",    "description": "Students on scholarship/discount plan.", "is_default": False},
    {"name": "Special Needs",  "description": "Students requiring special support.",    "is_default": False},
    {"name": "Boarding",       "description": "Boarding students.",                     "is_default": False},
    {"name": "Staff Children", "description": "Children of staff members.",             "is_default": False},
]

# ------------------------------------------------------------
# Global Sections (seed once globally; no company_id)
# ------------------------------------------------------------
GLOBAL_SECTIONS: List[str] = ["A", "B", "C", "D", "E", "F", "G"]

# ------------------------------------------------------------
# Sessions + Timeslots
# ------------------------------------------------------------
DEFAULT_SCHOOL_SESSIONS: List[Dict[str, Any]] = [
    {"name": "Morning",   "start_time": time(7, 0),  "end_time": time(12, 15), "periods": 6},
    {"name": "Afternoon", "start_time": time(13, 0), "end_time": time(17, 20), "periods": 6},
]

# ------------------------------------------------------------
# EducationSettings defaults (only fill if missing; never override edits)
# ------------------------------------------------------------
DEFAULT_VALIDATE_BATCH_IN_STUDENT_GROUP = False
DEFAULT_ATTENDANCE_BASED_ON_COURSE_SCHEDULE = True
