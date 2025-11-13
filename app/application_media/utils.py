# app/common/media/utils.py
import os
import re
from typing import Tuple, Optional
from config.media_config import settings

_SAFE_SEG = re.compile(r"[^a-zA-Z0-9._/-]+")

def sanitize_segment(seg: str) -> str:
    return _SAFE_SEG.sub("-", seg).strip("-")

def validate_upload(filename: str, size_bytes: int) -> Tuple[bool, Optional[str]]:
    if not filename:
        return False, "Missing filename"
    if size_bytes > settings.MEDIA_MAX_MB * 1024 * 1024:
        return False, f"File too large (max {settings.MEDIA_MAX_MB} MB)"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext and ext not in settings.MEDIA_ALLOWED_EXTS:
        return False, f"File type not allowed. Allowed: {', '.join(settings.MEDIA_ALLOWED_EXTS)}"
    return True, None

class MediaFolder:
    """Canonical folder names for an ERP system."""
    COMPANIES = "companies_img"
    BRANCHES = "branches_img"
    EMPLOYEES = "employees_img"
    DATA_IMPORTS = "data_imports"

    # Add other entities like "products_img" or "vehicles_img" as needed.

def ensure_local_media_folders():
    """Create base media subfolders for local backend once at startup."""
    if settings.MEDIA_BACKEND.lower() != "local":
        return

    base = settings.LOCAL_MEDIA_ROOT
    folders = [
        MediaFolder.COMPANIES,
        MediaFolder.BRANCHES,
        MediaFolder.EMPLOYEES,
        MediaFolder.DATA_IMPORTS,
    ]

    os.makedirs(base, exist_ok=True)
    for f in folders:
        os.makedirs(os.path.join(base, f), exist_ok=True)