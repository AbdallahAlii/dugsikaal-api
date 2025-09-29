
# app/auth/me_service.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from app.application_media.encrypted_media import image_url_from_key
from app.auth.repo.me_repository import profile_repo
from app.common.cache.cache import cache_get, cache_set, get_version
from app.common.cache.cache_keys import user_profile_version_key, build_scoped_user_profile_cache_key


CACHE_TTL = 600  # seconds


def _brand_name(company: Dict[str, Any], branch: Optional[Dict[str, Any]]) -> str:
    return (branch and branch["name"]) or company["name"]


def _brand_logo_key(company: Dict[str, Any], branch: Optional[Dict[str, Any]]) -> Optional[str]:
    return (branch and branch.get("img_key")) or company.get("img_key")


class ProfileService:
    def _host_profile(self, *, user_id: int) -> Dict[str, Any]:
        """
        Host-scoped profile for system/host admins who have no company or branch.
        We try to fetch minimal user info; if the repository doesn't expose a helper,
        we gracefully fall back to generic values.
        """
        user_username = f"user-{user_id}"
        user_display = "System Admin"
        avatar_url: Optional[str] = None
        roles: list[str] = []

        # Best-effort optional lookups if repo exposes them
        try:
            if hasattr(profile_repo, "fetch_user_min"):
                u = profile_repo.fetch_user_min(user_id=user_id) or {}
                user_username = u.get("username") or user_username
                user_display = u.get("full_name") or u.get("username") or user_display
                if u.get("avatar_img_key"):
                    avatar_url = image_url_from_key(u["avatar_img_key"])
        except Exception as ex:
            logging.debug(f"[host_profile] fetch_user_min failed: {ex}")

        try:
            if hasattr(profile_repo, "fetch_roles_only"):
                roles = profile_repo.fetch_roles_only(user_id=user_id) or []
        except Exception as ex:
            logging.debug(f"[host_profile] fetch_roles_only failed: {ex}")

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
            },
            "roles": roles,
        }

    def get_me_profile(self, *, user_id: int, company_id: Optional[int], branch_id: Optional[int]) -> Dict[str, Any]:
        """
        Returns a profile envelope:
          • If company_id is provided: company/branch-scoped profile (existing behavior)
          • If company_id is None: host-scoped profile for system admins (no 401)
        """
        # cache key includes scope (company/branch may be None)
        v = get_version(user_profile_version_key(user_id), default=1)
        ckey = build_scoped_user_profile_cache_key(user_id, v, company_id=company_id, branch_id=branch_id)

        cached = cache_get(ckey)
        if cached is not None:
            logging.info(f"✅ Cache HIT for key: {ckey}")
            return cached

        logging.info(f"❌ Cache MISS for key: {ckey}. Fetching from DB...")

        # Host-scoped: allow profile without company/branch
        if company_id is None:
            data = self._host_profile(user_id=user_id)
            cache_set(ckey, data, ttl=CACHE_TTL)
            return data

        # Company/branch-scoped behavior (your original flow)
        raw = profile_repo.fetch_core(user_id=user_id, company_id=company_id, branch_id=branch_id)
        if not raw:
            # If a specific branch scope failed, try company-only scope, then fallback to host
            if branch_id is not None:
                try:
                    fallback_raw = profile_repo.fetch_core(user_id=user_id, company_id=company_id, branch_id=None)
                except Exception:
                    fallback_raw = None
                if fallback_raw:
                    raw = fallback_raw
                else:
                    data = self._host_profile(user_id=user_id)
                    cache_set(ckey, data, ttl=CACHE_TTL)
                    return data
            else:
                data = self._host_profile(user_id=user_id)
                cache_set(ckey, data, ttl=CACHE_TTL)
                return data

        company, branch = raw["company"], raw["branch"]
        brand_key = _brand_logo_key(company, branch)
        brand_url = image_url_from_key(brand_key) if brand_key else None
        avatar_url = image_url_from_key(raw["user"]["avatar_img_key"]) if raw["user"].get("avatar_img_key") else None

        data = {
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
            },
            "roles": raw["roles"],
        }

        cache_set(ckey, data, ttl=CACHE_TTL)
        return data


profile_service = ProfileService()
