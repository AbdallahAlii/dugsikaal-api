# app/common/api_response.py
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from flask import jsonify

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """
    Standard API envelope for your ERP.
    """
    success: bool = Field(..., description="Whether the request was successful.")
    message: str = Field("", description="A human-readable message.")
    data: Optional[T] = Field(None, description="The result payload.")
    error_code: Optional[int] = Field(None, description="App-specific error code or HTTP status.")

    # Pydantic v2 config: allows serializing from ORM objects via attribute access
    model_config = ConfigDict(from_attributes=True)


def api_success(
    data: Optional[T] = None,
    message: str = "Success",
    status_code: int = 200,
):
    """
    Build a success JSON response.
    Usage: return api_success({"id": 1}, "Created", 201)
    """
    payload = APIResponse(success=True, message=message, data=data, error_code=None).model_dump()
    return jsonify(payload), status_code


def api_error(
    message: str = "Error",
    *,
    status_code: int = 400,
    error_code: Optional[int] = None,
    data: Any = None,
):
    """
    Build an error JSON response.
    `status_code` sets HTTP status; `error_code` is optional app code.
    Usage: return api_error("Not authenticated", status_code=401)
    """
    payload = APIResponse(
        success=False,
        message=message,
        data=data,
        error_code=error_code or status_code,
    ).model_dump()
    return jsonify(payload), status_code
