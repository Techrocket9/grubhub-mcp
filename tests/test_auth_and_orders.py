from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from src.grubhub_mcp import auth as auth_module
from src.grubhub_mcp.tools import order as order_tools


class FakeSession:
    def __init__(self) -> None:
        self.auth_token = "token"
        self.refresh_token = "refresh"
        self.csrf_token = "csrf"
        self.diner_udid = None
        self.is_authenticated = True

    def set_authenticated(self, session_data: dict) -> None:
        self.auth_token = session_data.get("session_handle", {}).get("access_token", self.auth_token)
        credential = session_data.get("credential", {})
        self.diner_udid = credential.get("ud_id") or credential.get("udid") or self.diner_udid
        self.is_authenticated = True


class FakeClient:
    def __init__(self, history_orders: list[dict] | None = None) -> None:
        self.session = FakeSession()
        self.session.diner_udid = "diner-123"
        self.history_orders = history_orders or []
        self.put_calls: list[tuple[str, dict, bool]] = []
        self.get_calls: list[tuple[str, dict | None, bool]] = []

    async def put(self, path: str, data: dict | None = None, auth_required: bool = True):
        self.put_calls.append((path, data or {}, auth_required))
        return {
            "session_handle": {"access_token": "new-token"},
        }

    async def get(self, path: str, params=None, auth_required: bool = True):
        self.get_calls.append((path, params, auth_required))
        if path == "/session":
            return {
                "credential": {"ud_id": "otp-diner-456"},
                "session_handle": {"access_token": "new-token"},
            }
        if path.startswith("/orders/"):
            request = httpx.Request("GET", f"https://api-gtm.grubhub.com{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        if path == f"/diners/{self.session.diner_udid}/orders":
            return {"orders": self.history_orders}
        raise AssertionError(f"unexpected GET path: {path}")


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class AuthAndOrdersTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_otp_fetches_session_when_udid_missing(self):
        client = FakeClient()
        client.session.diner_udid = None

        await auth_module.verify_otp(client, "user@example.com", "123456")

        self.assertEqual(client.session.diner_udid, "otp-diner-456")
        self.assertEqual(client.get_calls[0][0], "/session")

    async def test_get_order_history_paginates_client_side(self):
        history_orders = [
            {"id": f"order-{i}", "group_id": f"group-{i}"} for i in range(5)
        ]
        client = FakeClient(history_orders=history_orders)
        mcp = FakeMCP()
        order_tools.register(mcp)

        with patch("src.grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order_history"](page_size=2, page_num=1)

        data = json.loads(raw)
        self.assertEqual([o["id"] for o in data["orders"]], ["order-2", "order-3"])
        self.assertEqual(data["pagination"]["total_orders"], 5)
        self.assertEqual(data["pagination"]["returned"], 2)

    async def test_get_order_falls_back_to_history_lookup_on_404(self):
        history_orders = [
            {"id": "order-1", "group_id": "group-1", "name": "first"},
            {"id": "order-2", "group_id": "group-2", "name": "second"},
        ]
        client = FakeClient(history_orders=history_orders)
        mcp = FakeMCP()
        order_tools.register(mcp)

        with patch("src.grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order"]("group-2")

        data = json.loads(raw)
        self.assertEqual(data["id"], "order-2")
        self.assertEqual(data["group_id"], "group-2")


if __name__ == "__main__":
    unittest.main()
