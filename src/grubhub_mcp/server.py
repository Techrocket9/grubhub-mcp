"""Grubhub MCP Server — search restaurants, browse menus, manage cart, place orders."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import close_client
from .tools import account, auth, cart, order, payments, restaurant, search


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Close the shared HTTP client when the server shuts down."""
    try:
        yield {}
    finally:
        await close_client()


mcp = FastMCP(
    "grubhub",
    instructions=(
        "Grubhub MCP server. Use these tools to search for restaurants, "
        "browse menus, manage a shopping cart, place food delivery/pickup "
        "orders, and manage your Grubhub account. "
        "Start by searching for restaurants near a location. "
        "Login is required for placing orders, viewing order history, "
        "and account management. Search and menu browsing work without login. "
        "place_order, post_delivery_tip and apply_gift_card spend real money "
        "and cannot be undone — always show the user the cart total and get an "
        "explicit confirmation before calling them."
    ),
    lifespan=_lifespan,
)

# Register all tool modules
auth.register(mcp)
search.register(mcp)
restaurant.register(mcp)
cart.register(mcp)
order.register(mcp)
account.register(mcp)
payments.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
