# application_data_import/queries/logs.py
from __future__ import annotations
from typing import Dict, Any, List

from config.database import db
from ..models import DataImportLog


def list_logs(data_import_id: int, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
    q = db.session.query(DataImportLog).filter(DataImportLog.data_import_id == data_import_id)
    total = q.count()
    rows = q.order_by(DataImportLog.row_index.asc()).offset((page - 1) * per_page).limit(per_page).all()
    data: List[Dict[str, Any]] = [
        {"row_index": r.row_index, "success": r.success, "messages": r.messages} for r in rows
    ]
    return {"total": total, "data": data}
