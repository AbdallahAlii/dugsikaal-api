from sqlalchemy import select, delete
from app.navigation_workspace.models.nav_links import Workspace
from app.navigation_workspace.models.workspace_roles import WorkspaceRole
from .workspace_roles import WORKSPACE_ROLES


def seed_workspace_roles(session):
    """
    ERPNext-style, SAFE, idempotent seeder.

    - Seeds only EXISTING workspaces
    - Skips missing workspaces (HR, Platform, etc.)
    - No duplicates
    - Safe to re-run
    """

    for slug, roles in WORKSPACE_ROLES.items():
        ws = session.execute(
            select(Workspace).where(Workspace.slug == slug)
        ).scalar_one_or_none()

        # -------------------------------------------------
        # 🚫 Workspace not installed / not present
        # -------------------------------------------------
        if ws is None:
            print(f"⚠️  Skipping workspace '{slug}' (not found)")
            continue

        desired_roles = {r.strip() for r in roles if r}

        existing_roles = set(
            session.execute(
                select(WorkspaceRole.role_name).where(
                    WorkspaceRole.workspace_id == ws.id
                )
            ).scalars().all()
        )

        # -------------------------------------------------
        # Insert missing roles
        # -------------------------------------------------
        for role in desired_roles - existing_roles:
            session.add(
                WorkspaceRole(
                    workspace_id=ws.id,
                    role_name=role,
                )
            )

        # -------------------------------------------------
        # OPTIONAL strict cleanup (OFF by default)
        # -------------------------------------------------
        # session.execute(
        #     delete(WorkspaceRole).where(
        #         WorkspaceRole.workspace_id == ws.id,
        #         WorkspaceRole.role_name.not_in(desired_roles),
        #     )
        # )

    session.flush()
