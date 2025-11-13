# application_data_import/parsers/__init__.py
from __future__ import annotations
from .csv_reader import read_csv_bytes
from .xlsx_reader import read_xlsx_bytes
from .sheets_reader import read_google_sheet
