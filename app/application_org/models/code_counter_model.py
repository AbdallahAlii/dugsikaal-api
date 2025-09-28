from __future__ import annotations
from enum import Enum
from typing import Optional

from sqlalchemy import UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from config.database import db
from app.common.models.base import BaseModel


class CodeScopeEnum(str, Enum):
    GLOBAL = "GLOBAL"    # no company/branch
    COMPANY = "COMPANY"  # per company
    BRANCH = "BRANCH"    # per branch


class ResetPolicyEnum(str, Enum):
    NEVER = "NEVER"
    YEARLY = "YEARLY"
    MONTHLY = "MONTHLY"


class CodeType(BaseModel):
    __tablename__ = "code_types"

    name: Mapped[str] = mapped_column(db.String(100), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(db.String(50), nullable=False, unique=True, index=True)

    # Tokens: {PREFIX}, {YYYY}, {MM}, {SEQ}
    pattern: Mapped[str] = mapped_column(db.String(120), nullable=False, default="{PREFIX}-{SEQ}")

    scope: Mapped[CodeScopeEnum] = mapped_column(
        db.Enum(CodeScopeEnum, name="code_scope_enum"),
        nullable=False,
        default=CodeScopeEnum.COMPANY,
        index=True,
    )
    reset_policy: Mapped[ResetPolicyEnum] = mapped_column(
        db.Enum(ResetPolicyEnum, name="code_reset_policy_enum"),
        nullable=False,
        default=ResetPolicyEnum.NEVER,
        index=True,
    )
    padding: Mapped[int] = mapped_column(db.Integer, nullable=False, default=5)

    __table_args__ = (
        Index("ix_code_type_name_prefix", "name", "prefix"),
    )

    def __repr__(self) -> str:
        return f"<CodeType id={self.id} {self.prefix} {self.scope}/{self.reset_policy}>"


class CodeCounter(BaseModel):
    """
    One row per (code_type, scope partition, period_key).
    period_key:
      NEVER   -> NULL
      YEARLY  -> 'YYYY'
      MONTHLY -> 'YYYY-MM'
    """
    __tablename__ = "code_counters"

    code_type_id: Mapped[int] = mapped_column(
        db.BigInteger, db.ForeignKey("code_types.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        db.BigInteger, db.ForeignKey("branches.id", ondelete="CASCADE"), nullable=True, index=True
    )
    period_key: Mapped[Optional[str]] = mapped_column(db.String(20), nullable=True, index=True)
    last_sequence_number: Mapped[int] = mapped_column(db.BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("code_type_id", "company_id", "branch_id", "period_key",
                         name="uq_code_counter_partition"),
        Index("ix_code_counter_company", "company_id"),
        Index("ix_code_counter_branch", "branch_id"),
    )

    code_type: Mapped["CodeType"] = relationship("CodeType", lazy="joined")

    def __repr__(self) -> str:
        return (f"<CodeCounter type={self.code_type_id} "
                f"co={self.company_id} br={self.branch_id} per={self.period_key} seq={self.last_sequence_number}>")
