from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from src.grubhub_mcp import auth as auth_module
from src.grubhub_mcp.tools import auth as auth_tools
from src.grubhub_mcp.tools import cart as cart_tools
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
        self.post_calls: list[tuple[str, dict | None, bool, dict | None]] = []

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

    async def post(
        self,
        path: str,
        data: dict | None = None,
        auth_required: bool = True,
        params: dict | None = None,
    ):
        self.post_calls.append((path, data, auth_required, params))
        if path.startswith("/orders/") and path.endswith("/reorder"):
            request = httpx.Request("POST", f"https://api-gtm.grubhub.com{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        if path == "/carts":
            return {"id": "cart-123", "already_exists": False}
        raise AssertionError(f"unexpected POST path: {path}")


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

    async def test_verify_login_otp_maps_401_to_friendly_error(self):
        client = FakeClient()
        mcp = FakeMCP()
        auth_tools.register(mcp)
        request = httpx.Request("PUT", "https://api-gtm.grubhub.com/auth/confirmation_code")
        response = httpx.Response(401, request=request)

        with (
            patch("src.grubhub_mcp.tools.auth.get_client", return_value=client),
            patch(
                "src.grubhub_mcp.tools.auth.auth_module.verify_otp",
                side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response),
            ),
        ):
            raw = await mcp.tools["verify_login_otp"]("user@example.com", "000000")

        data = json.loads(raw)
        self.assertEqual(
            data,
            {"error": "OTP expired or invalid — request a new code with send_login_otp"},
        )

    async def test_create_cart_omits_invalid_when_for_payload_field(self):
        client = FakeClient()
        mcp = FakeMCP()
        cart_tools.register(mcp)

        with patch("src.grubhub_mcp.tools.cart.get_client", return_value=client):
            raw = await mcp.tools["create_cart"](
                restaurant_id="11278616",
                menu_item_id="322296812576",
                quantity=1,
                latitude=42.3601,
                longitude=-71.0589,
                is_delivery=True,
            )

        data = json.loads(raw)
        self.assertEqual(data["id"], "cart-123")
        self.assertEqual(len(client.post_calls), 1)
        path, payload, auth_required, params = client.post_calls[0]
        self.assertEqual(path, "/carts")
        self.assertTrue(auth_required)
        self.assertIsNone(params)
        assert payload is not None
        self.assertNotIn("when_for", payload)
        self.assertEqual(payload["order_type"], "DELIVERY")
        self.assertEqual(payload["restaurant_id"], "11278616")

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

    async def test_get_order_returns_friendly_auth_error_when_logged_out(self):
        client = FakeClient(history_orders=[])
        client.session.is_authenticated = False
        client.session.diner_udid = None
        mcp = FakeMCP()
        order_tools.register(mcp)

        with patch("src.grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order"]("order-1")

        data = json.loads(raw)
        self.assertEqual(data, {"error": "Must be logged in to view order details"})

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

    async def test_reorder_falls_back_to_cart_reconstruction_on_404(self):
        history_orders = [
            {
                "id": "order-2",
                "group_id": "group-2",
                "restaurants": [{"id": "2056994"}],
                "fulfillment_info": {"type": "PICKUP"},
                "charges": {
                    "lines": {
                        "line_items": [
                            {
                                "menu_item_id": "324325110600",
                                "quantity": 1,
                                "options": [{"id": "324325089912", "quantity": 1}],
                            }
                        ]
                    }
                },
            }
        ]
        client = FakeClient(history_orders=history_orders)
        mcp = FakeMCP()
        order_tools.register(mcp)

        with patch("src.grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["reorder"]("group-2")

        data = json.loads(raw)
        self.assertEqual(data["id"], "cart-123")
        self.assertEqual(client.post_calls[0][0], "/orders/group-2/reorder")
        self.assertEqual(client.post_calls[1][0], "/carts")
        payload = client.post_calls[1][1]
        assert payload is not None
        self.assertEqual(payload["restaurant_id"], "2056994")
        self.assertEqual(payload["order_type"], "PICKUP")
        self.assertEqual(payload["line_items"][0]["menu_item_id"], "324325110600")


if __name__ == "__main__":
    unittest.main()
