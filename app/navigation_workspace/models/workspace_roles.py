# app/navigation_workspace/models/workspace_roles.py

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from config.database import db
from app.common.models.base import BaseModel


class WorkspaceRole(BaseModel):
    """
    ERPNext equivalent:
      - tabHas Role (linked to tabModule Def)
    """

    __tablename__ = "workspace_roles"

    workspace_id: Mapped[int] = mapped_column(
        db.BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role_name: Mapped[str] = mapped_column(
        db.String(100),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "role_name", name="uq_workspace_role"),
    )

    def __repr__(self) -> str:
        return f"<WorkspaceRole workspace={self.workspace_id} role={self.role_name}>"
