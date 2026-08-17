"""Restaurant and menu MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import get_client
from ._common import handle_api_errors, json_result


def _location_params(
    params: dict[str, Any], latitude: float | None, longitude: float | None
) -> dict[str, Any]:
    """Attach a POINT() location when both coordinates were supplied.

    Uses ``is not None`` so a legitimate 0.0 coordinate (equator/prime
    meridian) is not silently dropped.
    """
    if latitude is not None and longitude is not None:
        params["location"] = f"POINT({longitude} {latitude})"
    return params


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get restaurant details",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_restaurant(
        restaurant_id: str,
        latitude: float | None = None,
        longitude: float | None = None,
        order_type: str = "standard",
    ) -> str:
        """Get restaurant details including menu, hours, ratings, and delivery
        info. Read-only, no login needed.

        Args:
            restaurant_id: The Grubhub restaurant ID
            latitude: Optional latitude for delivery estimates
            longitude: Optional longitude for delivery estimates
            order_type: Order type - standard, catering (default standard)
        """
        client = get_client()

        params: dict[str, Any] = {
            "orderType": order_type,
            "hideUnavailableMenuItems": True,
            "hideChoiceCategories": True,
        }
        _location_params(params, latitude, longitude)

        data = await client.get(f"/restaurants/v4/{restaurant_id}", params=params)
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get restaurant menu",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_menu(
        restaurant_id: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> str:
        """Get the full menu for a restaurant including categories, items, and
        prices. Read-only, no login needed.

        This is the same as get_restaurant — the v4 endpoint returns the full menu.

        Args:
            restaurant_id: The Grubhub restaurant ID
            latitude: Optional latitude for availability
            longitude: Optional longitude for availability
        """
        client = get_client()

        params: dict[str, Any] = {
            "orderType": "standard",
            "hideUnavailableMenuItems": True,
        }
        _location_params(params, latitude, longitude)

        data = await client.get(f"/restaurants/v4/{restaurant_id}", params=params)
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get menu item details",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_menu_item(
        restaurant_id: str,
        item_id: str,
        order_type: str = "standard",
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> str:
        """Get details for a specific menu item including options, add-ons, and
        pricing. Read-only, no login needed.

        Args:
            restaurant_id: The Grubhub restaurant ID
            item_id: The menu item ID
            order_type: Order type - standard, catering (default standard)
            latitude: Optional latitude for availability
            longitude: Optional longitude for availability
        """
        client = get_client()

        params: dict[str, Any] = {
            "orderType": order_type,
            "hideUnavailableMenuItems": True,
        }
        _location_params(params, latitude, longitude)

        data = await client.get(
            f"/restaurants/v4/{restaurant_id}/menu_items/{item_id}",
            params=params,
        )
        return json_result(data)
