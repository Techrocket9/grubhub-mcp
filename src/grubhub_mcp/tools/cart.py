"""Cart management MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import get_client
from ._common import handle_api_errors, json_result, require_int, to_cents

MAX_QUANTITY = 100


def _build_line_item(
    menu_item_id: str,
    quantity: int,
    special_instructions: str,
    options: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    line_item: dict[str, Any] = {
        "menu_item_id": menu_item_id,
        "quantity": require_int(
            quantity, "quantity", minimum=1, maximum=MAX_QUANTITY
        ),
    }
    if special_instructions:
        line_item["special_instructions"] = special_instructions
    if options:
        line_item["options"] = options
    return line_item


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Create cart",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def create_cart(
        restaurant_id: str,
        menu_item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
        options: list[dict[str, Any]] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        is_delivery: bool = True,
    ) -> str:
        """Create a new cart with the first item. Nothing is charged until
        place_order is called.

        Args:
            restaurant_id: The restaurant ID to order from
            menu_item_id: The menu item ID to add
            quantity: Number of this item (default 1)
            special_instructions: Special preparation instructions
            options: List of selected options/add-ons, each with {id, quantity}
            latitude: Delivery latitude
            longitude: Delivery longitude
            is_delivery: True for delivery, False for pickup
        """
        client = get_client()

        line_item = _build_line_item(
            menu_item_id, quantity, special_instructions, options
        )

        payload: dict[str, Any] = {
            "brand": "GRUBHUB",
            "restaurant_id": restaurant_id,
            "line_items": [line_item],
            "order_type": "DELIVERY" if is_delivery else "PICKUP",
        }
        if latitude is not None and longitude is not None:
            payload["location"] = {
                "latitude": latitude,
                "longitude": longitude,
            }

        data = await client.post("/carts", data=payload)
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get cart",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_cart(cart_id: str) -> str:
        """Get the current state of a cart including items, totals, and fees.

        Args:
            cart_id: The cart ID
        """
        client = get_client()
        data = await client.get(f"/carts/{cart_id}")
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Add item to cart",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def add_to_cart(
        cart_id: str,
        menu_item_id: str,
        quantity: int = 1,
        special_instructions: str = "",
        options: list[dict[str, Any]] | None = None,
    ) -> str:
        """Add an item to an existing cart. Nothing is charged until
        place_order is called.

        Args:
            cart_id: The cart ID to add to
            menu_item_id: The menu item ID to add
            quantity: Number of this item (default 1)
            special_instructions: Special preparation instructions
            options: List of selected options/add-ons, each with {id, quantity}
        """
        client = get_client()

        line_item = _build_line_item(
            menu_item_id, quantity, special_instructions, options
        )

        data = await client.post(f"/carts/{cart_id}/line_items", data=line_item)
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Update cart item quantity",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def update_cart_item(cart_id: str, line_item_id: str, quantity: int) -> str:
        """Update the quantity of an item in the cart.

        Args:
            cart_id: The cart ID
            line_item_id: The line item ID to update
            quantity: New quantity (0 removes the item)
        """
        client = get_client()
        quantity = require_int(quantity, "quantity", minimum=0, maximum=MAX_QUANTITY)
        data = await client.put(
            f"/carts/{cart_id}/line_items/{line_item_id}",
            data={"quantity": quantity},
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Remove item from cart",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def remove_from_cart(cart_id: str, line_item_id: str) -> str:
        """Remove an item from the cart.

        Args:
            cart_id: The cart ID
            line_item_id: The line item ID to remove
        """
        client = get_client()
        data = await client.delete(f"/carts/{cart_id}/line_items/{line_item_id}")
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Apply promo code",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def apply_promo_code(cart_id: str, promo_code: str) -> str:
        """Apply a promotion code to the cart.

        Args:
            cart_id: The cart ID
            promo_code: The promotion code to apply
        """
        client = get_client()
        data = await client.post(
            f"/carts/{cart_id}/promotions",
            data={"promo_code": promo_code},
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Set cart tip",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def set_tip(cart_id: str, tip_amount: float) -> str:
        """Set the tip amount on the cart. Charged with the order when
        place_order is called.

        Args:
            cart_id: The cart ID
            tip_amount: Tip amount in dollars (e.g. 5.25)
        """
        client = get_client()
        data = await client.put(
            f"/carts/{cart_id}/tip",
            data={"tip_amount": to_cents(tip_amount)},  # cents
        )
        return json_result(data)
