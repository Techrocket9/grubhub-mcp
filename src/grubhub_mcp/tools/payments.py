"""Payment management MCP tools."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import get_client
from ._common import handle_api_errors, json_result, require_authenticated


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get saved payment methods",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_payment_methods() -> str:
        """Get saved payment methods. Requires authentication."""
        client = get_client()
        auth_error = require_authenticated(client, "view payment methods")
        if auth_error:
            return auth_error

        data = await client.get(f"/payments/{client.session.diner_udid}/payments")
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Check gift card balance",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def get_gift_card_balance(card_number: str, pin: str) -> str:
        """Check the balance of a Grubhub gift card. Read-only — does not spend
        the card. The card number and PIN pass through this tool call, so only
        use values the user supplied.

        Args:
            card_number: Gift card number
            pin: Gift card PIN
        """
        client = get_client()
        data = await client.post(
            "/gift_cards/balance",
            data={"card_number": card_number, "pin": pin},
        )
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Apply gift card to cart (spends balance)",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def apply_gift_card(cart_id: str, card_number: str, pin: str) -> str:
        """Attach a gift card to a cart as a payment method. The balance is
        consumed when the order is placed, and applying a card cannot be undone
        from this server. Only call it when the user explicitly asked to pay
        with this card.

        Args:
            cart_id: The cart ID
            card_number: Gift card number
            pin: Gift card PIN
        """
        client = get_client()
        data = await client.post(
            f"/carts/{cart_id}/payments/gift_card",
            data={"card_number": card_number, "pin": pin},
        )
        return json_result(data)
