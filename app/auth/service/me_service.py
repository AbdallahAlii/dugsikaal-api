# app/auth/me_service.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from config.database import db
from app.application_media.encrypted_media import image_url_from_key
from app.auth.repo.me_repository import profile_repo
from app.common.cache.cache import get_or_build_list
from app.common.timezone.service import get_company_timezone

log = logging.getLogger(__name__)

CACHE_TTL = 600  # seconds

def _brand_name(company: Dict[str, Any], branch: Optional[Dict[str, Any]]) -> str:
    return (branch and branch["name"]) or company["name"]

def _brand_logo_key(company: Dict[str, Any], branch: Optional[Dict[str, Any]]) -> Optional[str]:
    return (branch and branch.get("img_key")) or company.get("img_key")

class ProfileService:
    def _host_profile(self, *, user_id: int) -> Dict[str, Any]:
        user_username = f"user-{user_id}"
        user_display = "System Admin"
        avatar_url: Optional[str] = None
        roles: list[str] = []

        try:
            if hasattr(profile_repo, "fetch_user_min"):
                u = profile_repo.fetch_user_min(user_id=user_id) or {}
                user_username = u.get("username") or user_username
                user_display = u.get("full_name") or u.get("username") or user_display
                if u.get("avatar_img_key"):
                    avatar_url = image_url_from_key(u["avatar_img_key"])
        except Exception as ex:
            log.debug("[host_profile] fetch_user_min failed: %s", ex)

        try:
            if hasattr(profile_repo, "fetch_roles_only"):
                roles = profile_repo.fetch_roles_only(user_id=user_id) or []
        except Exception as ex:
            log.debug("[host_profile] fetch_roles_only failed: %s", ex)

        return {
            "user": {
                "id": user_id,
                "username": user_username,
                "display_name": user_display,
                "avatar_url": avatar_url,
            },
            "context": {
                "company_id": None,
                "company_name": None,
                "branch_id": None,
                "branch_name": None,
                "job_title": None,
                "display_brand_name": "Platform Host",
                "display_brand_logo_url": None,
                "breadcrumb": [],
                "company_timezone": "Africa/Mogadishu",
            },
            "roles": roles,
        }

    def get_me_profile(
        self,
        *,
        user_id: int,
        company_id: Optional[int],
        branch_id: Optional[int],
    ) -> Dict[str, Any]:
        """
        Cached profile for the current user + scope.
        Redis is optional; if Redis is down this still returns DB result.
        """
        scope = f"u{int(user_id)}:c{int(company_id or 0)}:b{int(branch_id or 0)}"
        entity_scope = f"me_profile:{scope}"

        def _build() -> Dict[str, Any]:
            # Host-scoped
            if company_id is None:
                return self._host_profile(user_id=user_id)

            raw = profile_repo.fetch_core(user_id=user_id, company_id=company_id, branch_id=branch_id)

            # Fallback: if branch-specific is missing, try company scope
            if not raw and branch_id is not None:
                try:
                    raw = profile_repo.fetch_core(user_id=user_id, company_id=company_id, branch_id=None)
                except Exception:
                    raw = None

            # If still missing, fallback to host profile
            if not raw:
                return self._host_profile(user_id=user_id)

            company, branch = raw["company"], raw["branch"]
            brand_key = _brand_logo_key(company, branch)
            brand_url = image_url_from_key(brand_key) if brand_key else None
            avatar_url = (
                image_url_from_key(raw["user"]["avatar_img_key"])
                if raw["user"].get("avatar_img_key")
                else None
            )

            tz_str = "Africa/Mogadishu"
            try:
                tz_str = str(get_company_timezone(db.session, int(company["id"])))
            except Exception:
                pass

            return {
                "user": {
                    "id": raw["user"]["id"],
                    "username": raw["user"]["username"],
                    "display_name": raw["user"]["full_name"] or raw["user"]["username"],
                    "avatar_url": avatar_url,
                },
                "context": {
                    "company_id": raw["aff_scope"]["company_id"],
                    "company_name": company["name"],
                    "branch_id": raw["aff_scope"]["branch_id"],
                    "branch_name": branch["name"] if branch else None,
                    "job_title": raw["job_title"],
                    "display_brand_name": _brand_name(company, branch),
                    "display_brand_logo_url": brand_url,
                    "breadcrumb": (
                        [{"type": "company", "id": company["id"], "name": company["name"]}]
                        + ([{"type": "branch", "id": branch["id"], "name": branch["name"]}] if branch else [])
                    ),
                    "company_timezone": tz_str,
                },
                "roles": raw["roles"],
            }

        # params empty; if later you add language/theme flags etc, put them here.
        return get_or_build_list(
            entity_scope=entity_scope,
            params={},
            builder=_build,
            ttl=CACHE_TTL,
        )

profile_service = ProfileService()