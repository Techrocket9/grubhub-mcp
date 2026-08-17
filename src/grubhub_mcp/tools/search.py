"""Restaurant search and discovery MCP tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..client import get_client
from ._common import handle_api_errors, json_result, require_int

MAX_PAGE_SIZE = 100


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search restaurants",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def search_restaurants(
        latitude: float,
        longitude: float,
        query: str = "",
        page_size: int = 20,
        page_num: int = 1,
        sort_type: str = "",
        location_mode: str = "DELIVERY",
    ) -> str:
        """Search for restaurants near a location. Read-only, no login needed.

        Args:
            latitude: Latitude of the delivery address
            longitude: Longitude of the delivery address
            query: Optional search query (cuisine, restaurant name, dish)
            page_size: Number of results per page (default 20, max 100)
            page_num: Page number for pagination (1-based, default 1)
            sort_type: Optional sort — leave empty for default relevance
            location_mode: DELIVERY or PICKUP (default DELIVERY)
        """
        client = get_client()
        page_size = require_int(page_size, "page_size", minimum=1, maximum=MAX_PAGE_SIZE)
        page_num = require_int(page_num, "page_num", minimum=1)

        params: dict[str, Any] = {
            "location": f"POINT({longitude} {latitude})",
            "locationMode": location_mode,
            "facetSet": "umamiV6",
            "pageSize": page_size,
            "pageNum": page_num,
            "hideHateos": "true",
            "searchMetrics": "true",
            "preciseLocation": "true",
            "sortSetId": "umami",
            "countOmittingTimes": "true",
        }
        if query:
            params["queryText"] = query
        if sort_type:
            params["sorts"] = json.dumps({"sortType": sort_type})

        data = await client.get("/restaurants/search/search_listing", params=params)
        return json_result(data)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Autocomplete search",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    @handle_api_errors
    async def autocomplete_search(
        query: str,
        latitude: float,
        longitude: float,
        location_mode: str = "DELIVERY",
    ) -> str:
        """Get autocomplete suggestions for a search query. Read-only.

        Args:
            query: The partial search text
            latitude: Latitude for location context
            longitude: Longitude for location context
            location_mode: DELIVERY or PICKUP (default DELIVERY)
        """
        client = get_client()

        params = [
            ("lat", latitude),
            ("lng", longitude),
            ("prefix", query),
            ("locationMode", location_mode),
            ("resultTypeList", "restaurant"),
            ("resultTypeList", "restaurantPrediction"),
            ("resultTypeList", "dishTerm"),
        ]
        data = await client.get("/autocomplete", params=params)
        return json_result(data)
