"""Account management MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import get_client
from ._common import (
    error_result,
    handle_api_errors,
    json_result,
    require_authenticated,
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get profile",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_profile() -> str:
        """Get the current user's profile information. Requires authentication."""
        client = get_client()
        auth_error = require_authenticated(client, "view profile")
        if auth_error:
            return auth_error

        data = await client.get(
            f"/diners/{client.session.diner_udid}/details",
            params={
                "with_addresses": True,
                "with_favorites": True,
                "with_diner_identity": True,
                "with_phone_numbers": True,
            },
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Update profile",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def update_profile(
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
    ) -> str:
        """Overwrite the stored profile fields you pass. Requires authentication.

        Args:
            first_name: New first name
            last_name: New last name
            phone: New phone number
        """
        client = get_client()
        auth_error = require_authenticated(client, "update profile")
        if auth_error:
            return auth_error

        payload: dict[str, Any] = {}
        if first_name is not None:
            payload["first_name"] = first_name
        if last_name is not None:
            payload["last_name"] = last_name
        if phone is not None:
            payload["phone"] = phone
        if not payload:
            return error_result(
                "Nothing to update — pass at least one of first_name, "
                "last_name or phone"
            )

        data = await client.put(
            f"/credentials/{client.session.diner_udid}/profile",
            data=payload,
        )
        return json_result(data if data else {"status": "updated"})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get saved addresses",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_addresses() -> str:
        """Get saved delivery addresses. Requires authentication."""
        client = get_client()
        auth_error = require_authenticated(client, "view addresses")
        if auth_error:
            return auth_error

        data = await client.get(f"/diners/{client.session.diner_udid}/addresses")
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Add delivery address",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def add_address(
        street_address: str,
        city: str,
        state: str,
        zip_code: str,
        apt_suite: str = "",
        delivery_instructions: str = "",
        label: str = "",
    ) -> str:
        """Save a new delivery address on the account. Requires authentication.

        Args:
            street_address: Street address line
            city: City name
            state: State abbreviation (e.g. NY, CA)
            zip_code: ZIP code
            apt_suite: Apartment/suite number
            delivery_instructions: Special delivery instructions
            label: Label for the address (e.g. Home, Work)
        """
        client = get_client()
        auth_error = require_authenticated(client, "add addresses")
        if auth_error:
            return auth_error

        payload: dict[str, Any] = {
            "street_address": street_address,
            "city": city,
            "state": state,
            "zip_code": zip_code,
        }
        if apt_suite:
            payload["unit"] = apt_suite
        if delivery_instructions:
            payload["delivery_instructions"] = delivery_instructions
        if label:
            payload["label"] = label

        data = await client.post(
            f"/diners/{client.session.diner_udid}/addresses",
            data=payload,
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get favorite restaurants",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_favorites() -> str:
        """Get favorite/saved restaurants. Requires authentication."""
        client = get_client()
        auth_error = require_authenticated(client, "view favorites")
        if auth_error:
            return auth_error

        data = await client.get(
            f"/diners/{client.session.diner_udid}/favorites/restaurants"
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Add favorite restaurant",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def add_favorite(restaurant_id: str) -> str:
        """Add a restaurant to favorites. Requires authentication.

        Args:
            restaurant_id: The numeric Grubhub restaurant ID to favorite
        """
        client = get_client()
        auth_error = require_authenticated(client, "manage favorites")
        if auth_error:
            return auth_error

        try:
            numeric_id = int(str(restaurant_id).strip())
        except (TypeError, ValueError):
            return error_result(
                f"restaurant_id must be a numeric Grubhub restaurant ID, got {restaurant_id!r}"
            )

        data = await client.post(
            f"/diners/{client.session.diner_udid}/favorites/restaurants",
            data={"restaurant_id": numeric_id},
        )
        return json_result(data if data else {"status": "added"})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Remove favorite restaurant",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def remove_favorite(restaurant_id: str) -> str:
        """Remove a restaurant from favorites. Requires authentication.

        Args:
            restaurant_id: The restaurant ID to unfavorite
        """
        client = get_client()
        auth_error = require_authenticated(client, "manage favorites")
        if auth_error:
            return auth_error

        data = await client.delete(
            f"/diners/{client.session.diner_udid}/favorites/{restaurant_id}"
        )
        return json_result(data if data else {"status": "removed"})

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Change account password",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def change_password(current_password: str, new_password: str) -> str:
        """Change the account password. Requires authentication. Both passwords
        pass through this tool call, so only use it when the user explicitly
        asked to change their password.

        Args:
            current_password: Current password
            new_password: New password
        """
        client = get_client()
        auth_error = require_authenticated(client, "change your password")
        if auth_error:
            return auth_error

        data = await client.put(
            f"/credentials/{client.session.diner_udid}/change_password",
            data={
                "current_password": current_password,
                "new_password": new_password,
            },
        )
        return json_result(data if data else {"status": "password_changed"})
