from __future__ import annotations

from typing import Optional
import enum

from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from config.database import db
from app.common.models.base import BaseModel, StatusEnum


class FingerIndexEnum(str, enum.Enum):
    UNKNOWN = "Unknown"
    RIGHT_THUMB = "Right Thumb"
    RIGHT_INDEX = "Right Index"
    RIGHT_MIDDLE = "Right Middle"
    RIGHT_RING = "Right Ring"
    RIGHT_LITTLE = "Right Little"
    LEFT_THUMB = "Left Thumb"
    LEFT_INDEX = "Left Index"
    LEFT_MIDDLE = "Left Middle"
    LEFT_RING = "Left Ring"
    LEFT_LITTLE = "Left Little"


class EmployeeFingerprintTemplate(BaseModel):
    """
    Stores enrolled fingerprint template(s) per employee.
    Template bytes should be what your DP4500 SDK/exe returns (not image).
    """
    __tablename__ = "employee_fingerprint_templates"

    company_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    employee_id: Mapped[int] = mapped_column(
        db.BigInteger,
        db.ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    finger_index: Mapped[FingerIndexEnum] = mapped_column(
        db.Enum(FingerIndexEnum, name="finger_index_enum"),
        nullable=False,
        default=FingerIndexEnum.UNKNOWN,
        index=True,
    )

    # raw bytes from DP SDK/exe (store as BYTEA)
    template: Mapped[bytes] = mapped_column(db.LargeBinary, nullable=False)

    # metadata
    template_format: Mapped[str] = mapped_column(
        db.String(64),
        nullable=False,
        default="DP4500_TEMPLATE",
        comment="Format label for templates (e.g. DP U.are.U vX)",
    )

    device_name: Mapped[Optional[str]] = mapped_column(db.String(120))
    device_serial: Mapped[Optional[str]] = mapped_column(db.String(120))

    status: Mapped[StatusEnum] = mapped_column(
        db.Enum(StatusEnum, name="fingerprint_template_status_enum"),
        nullable=False,
        default=StatusEnum.ACTIVE,
        index=True,
    )

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "finger_index",
            name="uq_emp_fingerprint_finger"
        ),
        Index("ix_emp_fingerprint_company_emp", "company_id", "employee_id"),
    )

    employee = db.relationship("Employee", lazy="joined")
    company = db.relationship("Company", lazy="joined")

    def __repr__(self) -> str:
        return f"<EmployeeFingerprintTemplate emp={self.employee_id} finger={self.finger_index.value}>"
