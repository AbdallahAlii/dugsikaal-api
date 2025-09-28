# application_doctypes/core_lists/schemas.py
from __future__ import annotations
from typing import List, Dict, Any
from pydantic import BaseModel

class PaginationData(BaseModel):
    page: int
    per_page: int
    total_items: int
    total_pages: int

class ListResponse(BaseModel):
    data: List[Dict[str, Any]]
    pagination: PaginationData


class DetailResponse(BaseModel):
    data: Dict[str, Any]