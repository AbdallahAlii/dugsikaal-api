# application_data_import/schemas/dto.py
from __future__ import annotations
from typing import List, Optional, Any
try:
    from pydantic import BaseModel, Field
except Exception:
    from pydantic import BaseModel  # v1 fallback

from ..models import FileType, ImportType


class DownloadTemplateInput(BaseModel):
    reference_doctype: str
    file_type: FileType
    export_type: str                   # "blank" | "with_data"
    selected_fields: Optional[List[str]] = None


class StartImportInput(BaseModel):
    reference_doctype: str
    import_type: ImportType
    file_type: FileType
    mute_emails: bool = True
    submit_after_import: bool = False

    # Optional (when not using multipart form-data)
    filename: Optional[str] = None
    file_bytes: Optional[bytes] = None


class RetryImportInput(BaseModel):
    data_import_id: int


# -------- New UI/API-first flows --------

class CreateImportInput(BaseModel):
    """First step: create the DataImport record with only 3 essential fields."""
    reference_doctype: str
    import_type: ImportType
    file_type: FileType
    mute_emails: bool = True
    submit_after_import: bool = False  # 🔹 user decides if auto-submit is desired

    # 🔹 Optional override; if omitted, we use current user's context
    company_id: Optional[int] = None
    branch_id: Optional[int] = None



class SetTemplateFieldsInput(BaseModel):
    """Save user-selected columns in DB to be used by Download Template."""
    data_import_id: int
    fields: List[str] = Field(default_factory=list)  # ordered desired fields


class AttachFileInput(BaseModel):
    """Optional JSON route (if not using multipart)."""
    data_import_id: int
    filename: str
    file_bytes: bytes


class StartByIdInput(BaseModel):
    data_import_id: int
class SetTemplateFieldsBody(BaseModel):
    fields: List[str] = Field(default_factory=list)  # labels selected by the user