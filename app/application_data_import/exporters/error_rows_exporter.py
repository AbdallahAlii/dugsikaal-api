# application_data_import/exporters/error_rows_exporter.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple

from .csv_writer import write_csv
from .xlsx_writer import write_xlsx


def export_errors_as(headers: List[str], rows: List[Dict[str, Any]], reference_doctype: str, file_type: str = "csv") -> Tuple[bytes, str, str]:
    if file_type.lower() == "xlsx":
        content = write_xlsx(headers, rows)
        return content, f"{reference_doctype}_errored_rows.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = write_csv(headers, rows)
        return content, f"{reference_doctype}_errored_rows.csv", "text/csv"
