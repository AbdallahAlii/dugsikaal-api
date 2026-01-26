from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import requests


class QuranFoundationAuthError(RuntimeError):
    pass


class QuranFoundationOAuthClient:
    """
    OAuth2 Client Credentials for Quran Foundation.
    Caches token in-memory and refreshes shortly before expiry.
    """

    def __init__(
        self,
        oauth_base_url: str,
        client_id: str,
        client_secret: str,
        timeout: int = 30,
    ):
        self.oauth_base_url = oauth_base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        now = time.time()
        if self._access_token and now < (self._expires_at - 60):
            return self._access_token

        url = f"{self.oauth_base_url}/oauth2/token"
        data = "grant_type=client_credentials&scope=content"

        resp = requests.post(
            url,
            auth=(self.client_id, self.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            raise QuranFoundationAuthError(
                f"Failed to get token ({resp.status_code}): {resp.text}"
            )

        payload = resp.json()
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))

        if not token:
            raise QuranFoundationAuthError("Token response missing access_token")

        self._access_token = token
        self._expires_at = now + expires_in
        return token


class QuranApiClient:
    """
    Client for:
      - Quran Foundation Content API (OAuth2 + x-auth-token + x-client-id)
      - OR api.quran.com (no auth)

    If QF_CLIENT_ID/QF_CLIENT_SECRET are set AND base_url contains 'quran.foundation',
    OAuth headers are automatically attached.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 30,
        headers: Optional[Dict[str, str]] = None,
        default_params: Optional[Dict[str, Any]] = None,
    ):
        self.base_url = (
            base_url
            or os.getenv("QURAN_API_BASE_URL")
            or "https://api.quran.com/api/v4"
        ).rstrip("/")

        self.timeout = timeout
        self.session = requests.Session()
        self.default_params: Dict[str, Any] = default_params or {}

        if headers:
            self.session.headers.update(headers)

        # Quran Foundation OAuth config
        qf_client_id = os.getenv("QF_CLIENT_ID")
        qf_client_secret = os.getenv("QF_CLIENT_SECRET")
        oauth_base = os.getenv("QURAN_OAUTH_BASE_URL") or os.getenv("QF_OAUTH_BASE_URL")

        self._qf_client_id = qf_client_id
        self._oauth: Optional[QuranFoundationOAuthClient] = None

        if qf_client_id and qf_client_secret and oauth_base:
            self._oauth = QuranFoundationOAuthClient(
                oauth_base_url=oauth_base,
                client_id=qf_client_id,
                client_secret=qf_client_secret,
                timeout=timeout,
            )

    def _needs_qf_headers(self) -> bool:
        return "quran.foundation" in self.base_url and self._oauth is not None

    def _auth_headers(self) -> Dict[str, str]:
        if not self._oauth or not self._qf_client_id:
            return {}
        token = self._oauth.get_token()
        return {
            "x-auth-token": token,
            "x-client-id": self._qf_client_id,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"

        merged_params = dict(self.default_params)
        if params:
            merged_params.update(params)

        headers: Dict[str, str] = {}
        if self._needs_qf_headers():
            headers.update(self._auth_headers())

        resp = self.session.get(
            url, params=merged_params, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    # ------------- Chapters ------------- #

    def get_chapters(self, language: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if language:
            params["language"] = language
        return self._get("/chapters", params=params)

    # ------------- Verses ------------- #

    def get_verses_by_chapter(
        self,
        chapter_number: int,
        language: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
        words: bool = True,
        fields: Optional[Dict[str, bool]] = None,
        word_fields: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "words": "true" if words else "false",
        }
        if language:
            params["language"] = language

        if fields:
            for k, v in fields.items():
                params[f"fields[{k}]"] = "true" if v else "false"
        if word_fields:
            for k, v in word_fields.items():
                params[f"word_fields[{k}]"] = "true" if v else "false"

        return self._get(f"/verses/by_chapter/{chapter_number}", params=params)


def pick(d: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default
