"""Grubhub authentication flows."""

from __future__ import annotations

import logging
from typing import Any

from .client import API_KEY, GrubhubClient, GrubhubSession

logger = logging.getLogger(__name__)


async def create_anonymous_session(client: GrubhubClient) -> dict[str, Any]:
    """Create an anonymous session for unauthenticated browsing.

    Thin wrapper around :meth:`GrubhubClient._create_anonymous_session`; the
    implementation lives on the client so the request path can bootstrap a
    session itself without importing this module.
    """
    return await client._create_anonymous_session()


async def _backfill_diner_udid(client: GrubhubClient) -> None:
    """Fetch ``/session`` when an auth response omitted the diner id.

    Without ``diner_udid`` every authenticated tool refuses to run, so recover
    it rather than leaving the session half-usable. Best effort: the primary
    authentication already succeeded, so a failure here must not fail the login.
    """
    if client.session.diner_udid:
        return
    try:
        session_data = await get_session(client)
    except Exception:
        logger.debug("Could not backfill diner_udid from /session", exc_info=True)
        return
    client.session.set_authenticated(session_data)


async def login(client: GrubhubClient, email: str, password: str) -> dict[str, Any]:
    """Authenticate with email and password."""
    payload = {
        "brand": "GRUBHUB",
        "client_id": API_KEY,
        "email": email,
        "password": password,
    }
    data = await client.post("/auth/login", data=payload, auth_required=False)
    client.session.set_authenticated(data, require_token=True)
    await _backfill_diner_udid(client)
    return data


async def logout(client: GrubhubClient) -> dict[str, Any]:
    """Log out and clear session."""
    data: dict[str, Any] = {}
    if client.session.auth_token:
        try:
            data = await client.post("/auth/logout", auth_required=True)
        except Exception:
            data = {}
    client.session.clear()
    return data


async def get_session(client: GrubhubClient) -> dict[str, Any]:
    """Get current authenticated session info."""
    return await client.get("/session", auth_required=True)


async def send_otp(client: GrubhubClient, email: str) -> dict[str, Any]:
    """Send a one-time passcode for authentication."""
    # Ensure we have an anonymous session — Grubhub ties OTP to the bearer token
    await client.ensure_session()
    # A csrf_token from an earlier, abandoned OTP attempt must not be reused.
    client.session.csrf_token = None
    payload = {
        "brand": "GRUBHUB",
        "client_id": API_KEY,
        "email": email,
    }
    data = await client.post("/auth/confirmation_code", data=payload, auth_required=True)
    # Capture csrf_token from response — required for the verify step
    if isinstance(data, dict) and data.get("csrf_token"):
        client.session.csrf_token = data["csrf_token"]
    client.session._save()
    return data


async def verify_otp(client: GrubhubClient, email: str, code: str) -> dict[str, Any]:
    """Verify OTP and authenticate."""
    if not client.session.auth_token:
        raise ValueError("No session found — call send_login_otp first")
    if not client.session.csrf_token:
        raise ValueError("No csrf_token found — call send_login_otp first")
    payload = {
        "brand": "GRUBHUB",
        "client_id": API_KEY,
        "email": email,
        "csrf_token": client.session.csrf_token,
        "confirmation_code": code,
    }
    data = await client.put("/auth/confirmation_code", data=payload, auth_required=True)
    client.session.set_authenticated(data, require_token=True)
    # The code is single-use; drop it so a later verify cannot replay it.
    client.session.csrf_token = None
    # OTP responses sometimes omit credential metadata; fall back to /session.
    await _backfill_diner_udid(client)
    client.session._save()
    return data


async def create_account(
    client: GrubhubClient,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
) -> dict[str, Any]:
    """Create a new Grubhub account."""
    payload = {
        "brand": "GRUBHUB",
        "client_id": API_KEY,
        "email": email,
        "password": password,
        "first_name": first_name,
        "last_name": last_name,
    }
    data = await client.post("/credentials", data=payload, auth_required=False)
    # Signup does not always hand back a session. Only claim to be logged in
    # when a real access token came back, otherwise the auth guards would let
    # calls through on a stale anonymous token.
    access, _ = GrubhubSession._extract_tokens(data if isinstance(data, dict) else {})
    if access:
        client.session.set_authenticated(data, require_token=True)
        await _backfill_diner_udid(client)
    return data


async def get_account_details(client: GrubhubClient) -> dict[str, Any]:
    """Get account details for the current user."""
    if not client.session.diner_udid:
        return {"error": "Not authenticated"}
    return await client.get(f"/credentials/{client.session.diner_udid}")


async def send_password_reset_otp(client: GrubhubClient, email: str) -> dict[str, Any]:
    """Send OTP for password reset."""
    payload = {
        "brand": "GRUBHUB",
        "client_id": API_KEY,
        "email": email,
    }
    return await client.post(
        "/forgot_password/confirmation_code", data=payload, auth_required=False
    )
