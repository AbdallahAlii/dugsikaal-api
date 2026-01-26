# app/application_print/schemas/dto.py
from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel


class PrintOption(BaseModel):
    module: str
    entity: str
    doctype: str
    permission_tag: str


class PrintOptionListResponse(BaseModel):
    data: List[PrintOption]
    meta: Dict[str, str] | None = None
