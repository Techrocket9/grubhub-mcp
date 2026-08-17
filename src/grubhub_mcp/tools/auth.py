"""Authentication MCP tools."""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .. import auth as auth_module
from ..client import get_client
from ._common import error_result, handle_api_errors, json_result

EMAIL_ENV_VAR = "GRUBHUB_EMAIL"
PASSWORD_ENV_VAR = "GRUBHUB_PASSWORD"


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Log in to Grubhub",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def login(email: str | None = None, password: str | None = None) -> str:
        """Log in to Grubhub. Returns session info on success.

        Prefer calling this with NO arguments: credentials are then read from
        the GRUBHUB_EMAIL and GRUBHUB_PASSWORD environment variables, so the
        password never passes through the conversation. Only pass the arguments
        when the user has explicitly supplied them.

        Args:
            email: Account email. Defaults to $GRUBHUB_EMAIL.
            password: Account password. Defaults to $GRUBHUB_PASSWORD.
        """
        email = email or os.environ.get(EMAIL_ENV_VAR) or ""
        password = password or os.environ.get(PASSWORD_ENV_VAR) or ""
        if not email or not password:
            return error_result(
                "No credentials provided. Pass email and password, or set the "
                f"{EMAIL_ENV_VAR} and {PASSWORD_ENV_VAR} environment variables "
                "for the MCP server process."
            )

        client = get_client()
        await auth_module.login(client, email, password)
        result = {
            "status": "authenticated",
            "diner_udid": client.session.diner_udid,
            "email": email,
        }
        if not client.session.diner_udid:
            result["warning"] = (
                "Logged in but Grubhub did not return a diner id; account and "
                "order tools may not work until you log in again."
            )
        return json_result(result)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Log out",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def logout() -> str:
        """Log out of Grubhub and delete the locally stored session tokens."""
        client = get_client()
        await auth_module.logout(client)
        return json_result({"status": "logged_out"})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get session info",
            readOnlyHint=True,
            openWorldHint=False,
        )
    )
    @handle_api_errors
    async def get_session_info() -> str:
        """Get the current authentication state. Never returns the token itself."""
        client = get_client()
        return json_result(
            {
                "is_authenticated": client.session.is_authenticated,
                "diner_udid": client.session.diner_udid,
                "has_token": client.session.auth_token is not None,
            }
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Send login one-time passcode",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def send_login_otp(email: str) -> str:
        """Send a one-time login passcode to an email address.

        This sends real email to whatever address is given, so only use an
        address the user explicitly asked for.

        Args:
            email: The account email to send the passcode to
        """
        client = get_client()
        await auth_module.send_otp(client, email)
        return json_result({"status": "otp_sent", "email": email})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Verify login one-time passcode",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def verify_login_otp(email: str, code: str) -> str:
        """Verify a one-time passcode and complete login.

        Args:
            email: The email the passcode was sent to
            code: The passcode from the email
        """
        client = get_client()
        try:
            await auth_module.verify_otp(client, email, code)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return json_result(
                    {
                        "error": "OTP expired or invalid — request a new code with send_login_otp"
                    }
                )
            raise
        result = {
            "status": "authenticated",
            "diner_udid": client.session.diner_udid,
        }
        if not client.session.diner_udid:
            result["warning"] = (
                "Logged in but Grubhub did not return a diner id; account and "
                "order tools may not work until you log in again."
            )
        return json_result(result)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create a Grubhub account",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def create_account(
        email: str, password: str, first_name: str, last_name: str
    ) -> str:
        """Create a new Grubhub account. Registers a real account and sends
        email to the address given — only call this when the user has explicitly
        asked to sign up with that exact address.

        Args:
            email: Email address for the new account
            password: Password for the new account
            first_name: Account holder first name
            last_name: Account holder last name
        """
        client = get_client()
        await auth_module.create_account(
            client, email, password, first_name, last_name
        )
        return json_result(
            {
                "status": "account_created",
                "authenticated": client.session.is_authenticated,
                "diner_udid": client.session.diner_udid,
            }
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Send password reset email",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def send_password_reset(email: str) -> str:
        """Send a password reset passcode by email.

        This sends real email to whatever address is given, so only use an
        address the user explicitly asked for.

        Args:
            email: The account email to send the reset passcode to
        """
        client = get_client()
        await auth_module.send_password_reset_otp(client, email)
        return json_result({"status": "reset_otp_sent", "email": email})
