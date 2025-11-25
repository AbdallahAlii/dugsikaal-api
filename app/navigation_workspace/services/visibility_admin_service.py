from __future__ import annotations
from typing import Optional

from app.navigation_workspace.repo import NavRepository
from app.navigation_workspace.schemas import (
    SystemWorkspaceVisibilityIn,
    CompanyWorkspaceVisibilityIn,
)
from app.navigation_workspace.models.models_visibility import (
    SystemWorkspaceVisibility,
    CompanyWorkspaceVisibility,
)


class WorkspaceVisibilityAdminService:
    """
    Admin API for toggling visibility:
      - SystemWorkspaceVisibility (platform owner)
      - CompanyWorkspaceVisibility (tenant-level)
    """

    def __init__(self, repo: Optional[NavRepository] = None):
        self.repo = repo or NavRepository()

    def set_system_visibility(self, body: SystemWorkspaceVisibilityIn) -> SystemWorkspaceVisibility:
        ws = self.repo.find_workspace_by_slug(body.workspace_slug)
        if not ws:
            raise ValueError(f"Workspace not found: {body.workspace_slug}")
        row = self.repo.upsert_system_workspace_visibility(
            company_id=body.company_id,
            workspace_id=ws.id,
            is_enabled=body.is_enabled,
            reason=body.reason,
        )
        return row

    def set_company_visibility(self, body: CompanyWorkspaceVisibilityIn) -> CompanyWorkspaceVisibility:
        ws = self.repo.find_workspace_by_slug(body.workspace_slug)
        if not ws:
            raise ValueError(f"Workspace not found: {body.workspace_slug}")
        row = self.repo.upsert_company_workspace_visibility(
            company_id=body.company_id,
            workspace_id=ws.id,
            branch_id=body.branch_id,
            user_id=body.user_id,
            is_enabled=body.is_enabled,
            reason=body.reason,
        )
        return row
