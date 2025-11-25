#
# from __future__ import annotations
#
# from typing import Set
#
# from flask import Blueprint, g, request
#
# from app.auth.deps import get_current_user
# from app.common.api_response import api_error, api_success
# from app.navigation_workspace.services.directory_service import DocTypeDirectoryService
# from app.navigation_workspace.services.visibility_services import NavService
# from app.navigation_workspace.services.package_service import PackageService
# from app.navigation_workspace.services.visibility_admin_service import WorkspaceVisibilityAdminService
# from app.navigation_workspace.schemas import (
#     CompanyPackagesSetIn,
#     SystemWorkspaceVisibilityIn,
#     CompanyWorkspaceVisibilityIn,
# )
# from app.security.rbac_effective import AffiliationContext
#
# bp = Blueprint("navigation", __name__, url_prefix="api/navigation")
#
#
# def _ctx() -> AffiliationContext:
#     _ = get_current_user()
#     ctx: AffiliationContext = getattr(g, "auth", None)
#     if not ctx:
#         raise PermissionError("Unauthorized")
#     return ctx
#
#
# def _is_system_admin(context: AffiliationContext) -> bool:
#     if getattr(context, "is_system_admin", False):
#         return True
#     roles = {str(r).strip().lower() for r in getattr(context, "roles", []) if r}
#     return "system admin" in roles
#
#
# @bp.get("/nav/workspaces")
# def get_workspaces_nav():
#     try:
#         ctx = _ctx()
#         q_company = request.args.get("company_id", type=int)
#         q_branch = request.args.get("branch_id", type=int)
#
#         tree = NavService().build_nav_tree(
#             context=ctx,
#             company_id=q_company,
#             branch_id=q_branch,
#         )
#         if not tree.workspaces:
#             return api_success(
#                 data={"workspaces": []},
#                 message=(
#                     "You don’t have access to any modules. "
#                     "Please contact your administrator."
#                 ),
#             )
#         return api_success(tree.model_dump(), message="OK")
#
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception:
#         return api_error("Failed to build navigation.", status_code=500)
#
#
# @bp.get("/doctypes")
# def list_doctypes():
#     try:
#         ctx = _ctx()
#         perms: Set[str] = set(ctx.permissions or [])
#         directory = DocTypeDirectoryService().build_directory(perms=perms)
#
#         if not directory.doctypes:
#             return api_success(
#                 data={"doctypes": []},
#                 message=(
#                     "You don’t have access to any document types. "
#                     "Please contact your administrator."
#                 ),
#             )
#         return api_success(directory.model_dump(), message="OK")
#
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception:
#         return api_error("Failed to build DocType directory.", status_code=500)
#
#
# @bp.get("/doctypes/<string:slug>")
# def get_doctype(slug: str):
#     try:
#         ctx = _ctx()
#         perms: Set[str] = set(ctx.permissions or [])
#         details = DocTypeDirectoryService().get_doctype_details(
#             perms=perms,
#             slug=slug,
#         )
#         if not details:
#             return api_error("DocType not found or not permitted.", status_code=404)
#         return api_success(details.model_dump(), message="OK")
#
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception:
#         return api_error("Failed to load DocType.", status_code=500)
#
#
# # -------------------------------------------------------------
# # ADMIN: Module packages & subscriptions
# # -------------------------------------------------------------
#
# @bp.post("/admin/module-packages/sync")
# def sync_module_packages():
#     """
#     Host-level endpoint to sync ModulePackage + PackageWorkspace
#     from your MODULE_PACKAGES config.
#     """
#     try:
#         ctx = _ctx()
#         if not _is_system_admin(ctx):
#             return api_error("Forbidden", status_code=403)
#
#         # Adjust import path to where you defined MODULE_PACKAGES
#         from app.seed_data.subscription import MODULE_PACKAGES
#
#         svc = PackageService()
#         pkgs = svc.sync_from_config(MODULE_PACKAGES)
#         return api_success(
#             data={"count": len(pkgs)},
#             message="Module packages synced.",
#         )
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception:
#         return api_error("Failed to sync module packages.", status_code=500)
#
#
# @bp.post("/admin/companies/<int:company_id>/packages")
# def set_company_packages(company_id: int):
#     """
#     Host-level endpoint to assign packages to a company.
#     Body: CompanyPackagesSetIn
#     """
#     try:
#         ctx = _ctx()
#         if not _is_system_admin(ctx):
#             return api_error("Forbidden", status_code=403)
#
#         body_json = request.get_json(silent=True) or {}
#         body = CompanyPackagesSetIn(**body_json)
#
#         svc = PackageService()
#         out = svc.set_company_packages_for_company(company_id=company_id, body=body)
#         return api_success(out.model_dump(), message="Company packages updated.")
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception as e:
#         return api_error(f"Failed to set company packages: {e}", status_code=500)
#
#
# @bp.get("/admin/companies/<int:company_id>/packages")
# def get_company_packages(company_id: int):
#     try:
#         ctx = _ctx()
#         if not _is_system_admin(ctx):
#             return api_error("Forbidden", status_code=403)
#
#         svc = PackageService()
#         out = svc.get_company_packages(company_id=company_id)
#         return api_success(out.model_dump(), message="OK")
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except Exception as e:
#         return api_error(f"Failed to load company packages: {e}", status_code=500)
#
#
# # -------------------------------------------------------------
# # ADMIN: Workspace visibility
# # -------------------------------------------------------------
#
# @bp.post("/admin/system-workspace-visibility")
# def set_system_workspace_visibility():
#     """
#     Platform owner sets SystemWorkspaceVisibility row for (company, workspace).
#     """
#     try:
#         ctx = _ctx()
#         if not _is_system_admin(ctx):
#             return api_error("Forbidden", status_code=403)
#
#         body_json = request.get_json(silent=True) or {}
#         body = SystemWorkspaceVisibilityIn(**body_json)
#
#         svc = WorkspaceVisibilityAdminService()
#         row = svc.set_system_visibility(body)
#         return api_success(
#             data={
#                 "id": row.id,
#                 "company_id": row.company_id,
#                 "workspace_id": row.workspace_id,
#                 "is_enabled": row.is_enabled,
#                 "reason": row.reason,
#             },
#             message="System workspace visibility updated.",
#         )
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except ValueError as ve:
#         return api_error(str(ve), status_code=400)
#     except Exception as e:
#         return api_error(f"Failed to set system workspace visibility: {e}", status_code=500)
#
#
# @bp.post("/admin/company-workspace-visibility")
# def set_company_workspace_visibility():
#     """
#     Tenant admin-style override: company-wide / branch / user visibility.
#     (Still protected by system_admin in this example; you can relax later.)
#     """
#     try:
#         ctx = _ctx()
#         if not _is_system_admin(ctx):
#             return api_error("Forbidden", status_code=403)
#
#         body_json = request.get_json(silent=True) or {}
#         body = CompanyWorkspaceVisibilityIn(**body_json)
#
#         svc = WorkspaceVisibilityAdminService()
#         row = svc.set_company_visibility(body)
#         return api_success(
#             data={
#                 "id": row.id,
#                 "company_id": row.company_id,
#                 "workspace_id": row.workspace_id,
#                 "branch_id": row.branch_id,
#                 "user_id": row.user_id,
#                 "is_enabled": row.is_enabled,
#                 "reason": row.reason,
#             },
#             message="Company workspace visibility updated.",
#         )
#     except PermissionError:
#         return api_error("Unauthorized", status_code=401)
#     except ValueError as ve:
#         return api_error(str(ve), status_code=400)
#     except Exception as e:
#         return api_error(f"Failed to set company workspace visibility: {e}", status_code=500)
from __future__ import annotations

from typing import Set

from flask import Blueprint, g, request

from config.database import db  # ✅ IMPORTANT: import db to be able to commit

from app.auth.deps import get_current_user
from app.common.api_response import api_error, api_success
from app.navigation_workspace.services.directory_service import DocTypeDirectoryService
from app.navigation_workspace.services.visibility_services import NavService
from app.navigation_workspace.services.package_service import PackageService
from app.navigation_workspace.services.visibility_admin_service import WorkspaceVisibilityAdminService
from app.navigation_workspace.schemas import (
    CompanyPackagesSetIn,
    SystemWorkspaceVisibilityIn,
    CompanyWorkspaceVisibilityIn,
)
from app.security.rbac_effective import AffiliationContext

bp = Blueprint("navigation", __name__, url_prefix="/api/navigation")


def _ctx() -> AffiliationContext:
    _ = get_current_user()
    ctx: AffiliationContext = getattr(g, "auth", None)
    if not ctx:
        raise PermissionError("Unauthorized")
    return ctx


def _is_system_admin(context: AffiliationContext) -> bool:
    if getattr(context, "is_system_admin", False):
        return True
    roles = {str(r).strip().lower() for r in getattr(context, "roles", []) if r}
    return "system admin" in roles


# -------------------------------------------------------------
# NAV TREE + DOCTYPE DIRECTORY
# -------------------------------------------------------------

@bp.get("/nav/workspaces")
def get_workspaces_nav():
    try:
        ctx = _ctx()
        q_company = request.args.get("company_id", type=int)
        q_branch = request.args.get("branch_id", type=int)

        tree = NavService().build_nav_tree(
            context=ctx,
            company_id=q_company,
            branch_id=q_branch,
        )
        if not tree.workspaces:
            return api_success(
                data={"workspaces": []},
                message=(
                    "You don’t have access to any modules. "
                    "Please contact your administrator."
                ),
            )
        return api_success(tree.model_dump(), message="OK")

    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to build navigation.", status_code=500)


@bp.get("/doctypes")
def list_doctypes():
    try:
        ctx = _ctx()
        perms: Set[str] = set(ctx.permissions or [])
        directory = DocTypeDirectoryService().build_directory(perms=perms)

        if not directory.doctypes:
            return api_success(
                data={"doctypes": []},
                message=(
                    "You don’t have access to any document types. "
                    "Please contact your administrator."
                ),
            )
        return api_success(directory.model_dump(), message="OK")

    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to build DocType directory.", status_code=500)


@bp.get("/doctypes/<string:slug>")
def get_doctype(slug: str):
    try:
        ctx = _ctx()
        perms: Set[str] = set(ctx.permissions or [])
        details = DocTypeDirectoryService().get_doctype_details(
            perms=perms,
            slug=slug,
        )
        if not details:
            return api_error("DocType not found or not permitted.", status_code=404)
        return api_success(details.model_dump(), message="OK")

    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        return api_error("Failed to load DocType.", status_code=500)


# -------------------------------------------------------------
# ADMIN: Module packages & subscriptions
# -------------------------------------------------------------

@bp.post("/admin/module-packages/sync")
def sync_module_packages():
    """
    Host-level endpoint to sync ModulePackage + PackageWorkspace
    from your MODULE_PACKAGES config.
    """
    try:
        ctx = _ctx()
        if not _is_system_admin(ctx):
            return api_error("Forbidden", status_code=403)

        # Adjust import path to where you defined MODULE_PACKAGES
        from app.seed_data.subscription import MODULE_PACKAGES

        svc = PackageService()
        pkgs = svc.sync_from_config(MODULE_PACKAGES)

        # ✅ CRITICAL: persist module_packages + package_workspaces
        db.session.commit()

        return api_success(
            data={"count": len(pkgs)},
            message="Module packages synced.",
        )
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception:
        db.session.rollback()
        return api_error("Failed to sync module packages.", status_code=500)


@bp.post("/admin/companies/<int:company_id>/packages")
def set_company_packages(company_id: int):
    """
    Host-level endpoint to assign packages to a company.
    Body: CompanyPackagesSetIn
    """
    try:
        ctx = _ctx()
        if not _is_system_admin(ctx):
            return api_error("Forbidden", status_code=403)

        body_json = request.get_json(silent=True) or {}
        body = CompanyPackagesSetIn(**body_json)

        svc = PackageService()
        out = svc.set_company_packages_for_company(company_id=company_id, body=body)

        # ✅ CRITICAL: persist CompanyPackageSubscription rows
        db.session.commit()

        return api_success(out.model_dump(), message="Company packages updated.")
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        db.session.rollback()
        return api_error(f"Failed to set company packages: {e}", status_code=500)


@bp.get("/admin/companies/<int:company_id>/packages")
def get_company_packages(company_id: int):
    try:
        ctx = _ctx()
        if not _is_system_admin(ctx):
            return api_error("Forbidden", status_code=403)

        svc = PackageService()
        out = svc.get_company_packages(company_id=company_id)
        return api_success(out.model_dump(), message="OK")
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except Exception as e:
        return api_error(f"Failed to load company packages: {e}", status_code=500)


# -------------------------------------------------------------
# ADMIN: Workspace visibility
# -------------------------------------------------------------

@bp.post("/admin/system-workspace-visibility")
def set_system_workspace_visibility():
    """
    Platform owner sets SystemWorkspaceVisibility row for (company, workspace).
    """
    try:
        ctx = _ctx()
        if not _is_system_admin(ctx):
            return api_error("Forbidden", status_code=403)

        body_json = request.get_json(silent=True) or {}
        body = SystemWorkspaceVisibilityIn(**body_json)

        svc = WorkspaceVisibilityAdminService()
        row = svc.set_system_visibility(body)

        # ✅ persist visibility row
        db.session.commit()

        return api_success(
            data={
                "id": row.id,
                "company_id": row.company_id,
                "workspace_id": row.workspace_id,
                "is_enabled": row.is_enabled,
                "reason": row.reason,
            },
            message="System workspace visibility updated.",
        )
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except ValueError as ve:
        db.session.rollback()
        return api_error(str(ve), status_code=400)
    except Exception as e:
        db.session.rollback()
        return api_error(f"Failed to set system workspace visibility: {e}", status_code=500)


@bp.post("/admin/company-workspace-visibility")
def set_company_workspace_visibility():
    """
    Tenant admin-style override: company-wide / branch / user visibility.
    (Still protected by system_admin in this example; you can relax later.)
    """
    try:
        ctx = _ctx()
        if not _is_system_admin(ctx):
            return api_error("Forbidden", status_code=403)

        body_json = request.get_json(silent=True) or {}
        body = CompanyWorkspaceVisibilityIn(**body_json)

        svc = WorkspaceVisibilityAdminService()
        row = svc.set_company_visibility(body)

        # ✅ persist visibility row
        db.session.commit()

        return api_success(
            data={
                "id": row.id,
                "company_id": row.company_id,
                "workspace_id": row.workspace_id,
                "branch_id": row.branch_id,
                "user_id": row.user_id,
                "is_enabled": row.is_enabled,
                "reason": row.reason,
            },
            message="Company workspace visibility updated.",
        )
    except PermissionError:
        return api_error("Unauthorized", status_code=401)
    except ValueError as ve:
        db.session.rollback()
        return api_error(str(ve), status_code=400)
    except Exception as e:
        db.session.rollback()
        return api_error(f"Failed to set company workspace visibility: {e}", status_code=500)
