"""Grubhub HTTP client with authentication and header management."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api-gtm.grubhub.com"
AUTH_BASE_URL = "https://api-gtm.grubhub.com"
API_KEY = "ghandroid_Ujtwar5s9e3RYiSNV31X41y2hsK6Kh1Uv7JDrkpS"

# Directory permissions for the on-disk session cache. The file holds bearer and
# refresh tokens, so it must never be group/world readable.
_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Maximum number of characters of a non-JSON response body we will surface.
_MAX_RAW_BODY = 2000


def session_dir() -> Path:
    """Directory holding the persisted session.

    Resolved on every call so ``GRUBHUB_SESSION_DIR`` can be changed at runtime
    (and so tests can redirect it without reimporting the module).
    """
    override = os.environ.get("GRUBHUB_SESSION_DIR")
    if override:
        return Path(override)
    return Path.home() / ".grubhub-mcp"


def session_file() -> Path:
    """Path of the JSON file holding the persisted session."""
    return session_dir() / "session.json"


class GrubhubSession:
    """Manages authentication state for a Grubhub session."""

    def __init__(self) -> None:
        self.auth_token: str | None = None
        self.refresh_token: str | None = None
        self.diner_udid: str | None = None
        self.browser_id: str = str(uuid4())
        self.is_authenticated: bool = False
        self.session_handle: dict[str, Any] | None = None
        self.csrf_token: str | None = None
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _as_str(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    def _load(self) -> None:
        """Load persisted session from disk, tolerating corrupt/partial files."""
        try:
            path = session_file()
            if not path.exists():
                return
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                logger.debug("Persisted session is not a JSON object; ignoring")
                return
            self.auth_token = self._as_str(data.get("auth_token"))
            self.refresh_token = self._as_str(data.get("refresh_token"))
            self.diner_udid = self._as_str(data.get("diner_udid"))
            self.browser_id = self._as_str(data.get("browser_id")) or self.browser_id
            self.csrf_token = self._as_str(data.get("csrf_token"))
            handle = data.get("session_handle")
            self.session_handle = handle if isinstance(handle, dict) else None
            # A session is only usable as "authenticated" if it actually has a
            # bearer token and a diner id; otherwise every authenticated tool
            # would fail with a confusing error instead of asking for a login.
            self.is_authenticated = bool(
                data.get("is_authenticated") and self.auth_token and self.diner_udid
            )
        except Exception:
            logger.debug("Failed to load persisted session", exc_info=True)

    def _save(self) -> None:
        """Persist session state to disk with owner-only permissions.

        Written to a temporary file created with mode 0600 and then atomically
        renamed, so the token file is never briefly world-readable and a crash
        mid-write cannot leave a truncated session behind.
        """
        tmp_path: Path | None = None
        try:
            directory = session_dir()
            directory.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
            try:
                # mkdir's mode is subject to umask, and is not applied at all
                # when the directory already exists.
                directory.chmod(_DIR_MODE)
            except OSError:
                logger.debug("Could not tighten session directory permissions")

            payload = json.dumps(
                {
                    "auth_token": self.auth_token,
                    "refresh_token": self.refresh_token,
                    "diner_udid": self.diner_udid,
                    "browser_id": self.browser_id,
                    "is_authenticated": self.is_authenticated,
                    "session_handle": self.session_handle,
                    "csrf_token": self.csrf_token,
                }
            )

            target = session_file()
            tmp_path = target.with_name(f"{target.name}.{os.getpid()}.tmp")
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
            with os.fdopen(fd, "w") as handle:
                handle.write(payload)
            # O_CREAT's mode is masked by umask, so set it explicitly.
            os.chmod(tmp_path, _FILE_MODE)
            os.replace(tmp_path, target)
            tmp_path = None
        except Exception:
            logger.debug("Failed to persist session", exc_info=True)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tokens(session_data: dict[str, Any]) -> tuple[str | None, str | None]:
        handle = session_data.get("session_handle")
        handle = handle if isinstance(handle, dict) else {}
        access = handle.get("access_token") or session_data.get("auth_token")
        refresh = handle.get("refresh_token") or session_data.get("refresh_token")
        return (
            access if isinstance(access, str) and access else None,
            refresh if isinstance(refresh, str) and refresh else None,
        )

    def set_authenticated(
        self, session_data: dict[str, Any], require_token: bool = False
    ) -> None:
        """Record an authenticated session.

        Fields absent from ``session_data`` are preserved rather than cleared:
        refresh responses and ``/session`` payloads routinely omit ``credential``
        or ``refresh_token``, and blindly overwriting them used to wipe the
        diner id (breaking every authenticated tool) or the refresh token.

        Args:
            session_data: The API response body.
            require_token: Set for fresh logins (password/OTP/signup), where a
                response without an access token means the login did not work
                and must not be recorded as success.
        """
        if not isinstance(session_data, dict):
            raise ValueError("Unexpected authentication response from Grubhub")

        access, refresh = self._extract_tokens(session_data)
        if require_token and not access:
            raise ValueError(
                "Grubhub did not return an access token — the login was not completed"
            )
        if not access and not self.auth_token:
            raise ValueError(
                "Grubhub did not return an access token and no session is active"
            )

        if access:
            self.auth_token = access
        if refresh:
            self.refresh_token = refresh

        credential = session_data.get("credential")
        credential = credential if isinstance(credential, dict) else {}
        udid = credential.get("ud_id") or credential.get("udid")
        if isinstance(udid, str) and udid:
            self.diner_udid = udid

        handle = session_data.get("session_handle")
        if isinstance(handle, dict) and handle:
            self.session_handle = handle

        self.is_authenticated = True
        self._save()

    def set_anonymous(self, session_data: dict[str, Any]) -> None:
        """Record an anonymous (not logged in) session."""
        if not isinstance(session_data, dict):
            raise ValueError("Unexpected session response from Grubhub")

        access, refresh = self._extract_tokens(session_data)
        if not access:
            raise ValueError("Grubhub did not return an anonymous access token")

        self.auth_token = access
        if refresh:
            self.refresh_token = refresh

        handle = session_data.get("session_handle")
        if isinstance(handle, dict) and handle:
            self.session_handle = handle

        # An anonymous session is not tied to a diner account.
        self.diner_udid = None
        self.is_authenticated = False
        self._save()

    def clear(self) -> None:
        self.auth_token = None
        self.refresh_token = None
        self.diner_udid = None
        self.is_authenticated = False
        self.session_handle = None
        self.csrf_token = None
        try:
            path = session_file()
            if path.exists():
                path.unlink()
        except Exception:
            logger.debug("Failed to remove persisted session", exc_info=True)


class GrubhubClient:
    """HTTP client for Grubhub API with automatic auth handling."""

    def __init__(self) -> None:
        self.session = GrubhubSession()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=30.0,
            follow_redirects=True,
        )
        # Serializes anonymous-session creation and token refresh so concurrent
        # tool calls do not stampede /auth/anon or /auth/refresh.
        self._auth_lock = asyncio.Lock()

    def _headers(self, auth_required: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-gh-browser-id": self.session.browser_id,
            "Vary": "Accept-Encoding",
        }
        if self.session.auth_token and auth_required:
            headers["Authorization"] = f"Bearer {self.session.auth_token}"
        return headers

    # ------------------------------------------------------------------
    # Session bootstrap / refresh
    # ------------------------------------------------------------------

    async def _create_anonymous_session(self) -> dict[str, Any]:
        """Create an anonymous session (bearer token for unauthenticated use)."""
        payload = {
            "brand": "GRUBHUB",
            "client_id": API_KEY,
            "scope": "anonymous",
        }
        data = await self._request(
            "POST", "/auth/anon", json_body=payload, auth_required=False
        )
        self.session.set_anonymous(data)
        return data

    async def ensure_session(self) -> None:
        """Make sure a bearer token exists before an authenticated request.

        Grubhub rejects requests with no bearer token, so every authenticated
        code path (cart, payments, orders — not just search) needs this.
        """
        if self.session.auth_token:
            return
        async with self._auth_lock:
            if self.session.auth_token:
                return
            await self._create_anonymous_session()

    async def _refresh_token(self) -> bool:
        """Exchange the refresh token for a new access token."""
        if not self.session.refresh_token:
            return False
        try:
            resp = await self._http.post(
                "/auth/refresh",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "brand": "GRUBHUB",
                    "client_id": API_KEY,
                    "refresh_token": self.session.refresh_token,
                },
            )
            if not resp.is_success:
                return False
            data = resp.json()
            if not isinstance(data, dict):
                return False
            access, _ = GrubhubSession._extract_tokens(data)
            if not access:
                # Nothing usable came back; treat as a failed refresh instead of
                # retrying with the same expired token.
                return False
            if self.session.is_authenticated:
                self.session.set_authenticated(data)
            else:
                self.session.set_anonymous(data)
            return True
        except Exception:
            logger.debug("Token refresh failed", exc_info=True)
            return False

    async def _reauthenticate(self) -> bool:
        """Recover from a 401. Returns True if the request is worth retrying.

        On an unrecoverable failure the stale session is discarded: an expired
        persisted login would otherwise keep returning 401s forever with no hint
        that the user needs to log in again.
        """
        token_before = self.session.auth_token
        async with self._auth_lock:
            if self.session.auth_token != token_before:
                # Another concurrent call already refreshed.
                return True

            was_authenticated = self.session.is_authenticated
            if await self._refresh_token():
                return True

            self.session.clear()
            if was_authenticated:
                # The user must log in again; do not silently downgrade them to
                # an anonymous session and pretend the call can succeed.
                return False
            try:
                await self._create_anonymous_session()
            except Exception:
                logger.debug("Anonymous session recovery failed", exc_info=True)
                return False
            return True

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json_body: Any = None,
        auth_required: bool = True,
    ) -> dict[str, Any]:
        if auth_required:
            await self.ensure_session()

        resp = await self._http.request(
            method,
            path,
            headers=self._headers(auth_required),
            params=params,
            json=json_body,
        )
        if resp.status_code == 401 and auth_required:
            if await self._reauthenticate():
                resp = await self._http.request(
                    method,
                    path,
                    headers=self._headers(auth_required),
                    params=params,
                    json=json_body,
                )
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError:
            return {"raw_response": resp.text[:_MAX_RAW_BODY]}
        if isinstance(data, dict):
            return data
        return {"data": data}

    async def get(
        self, path: str, params: Any = None, auth_required: bool = True
    ) -> dict[str, Any]:
        return await self._request(
            "GET", path, params=params, auth_required=auth_required
        )

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        auth_required: bool = True,
        params: Any = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST", path, params=params, json_body=data, auth_required=auth_required
        )

    async def put(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        auth_required: bool = True,
        params: Any = None,
    ) -> dict[str, Any]:
        return await self._request(
            "PUT", path, params=params, json_body=data, auth_required=auth_required
        )

    async def delete(
        self, path: str, auth_required: bool = True, params: Any = None
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE", path, params=params, auth_required=auth_required
        )

    async def close(self) -> None:
        await self._http.aclose()


# Singleton client instance shared across tools
_client: GrubhubClient | None = None


def get_client() -> GrubhubClient:
    global _client
    if _client is None:
        _client = GrubhubClient()
    return _client


async def close_client() -> None:
    """Close and drop the shared client (called on server shutdown)."""
    global _client
    if _client is not None:
        client, _client = _client, None
        await client.close()
