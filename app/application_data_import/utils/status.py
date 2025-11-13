# application_data_import/utils/status.py
from __future__ import annotations
from ..models import DataImport, ImportStatus

def set_status(di: DataImport, status: ImportStatus) -> None:
    di.status = status
