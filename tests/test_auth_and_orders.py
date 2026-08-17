from __future__ import annotations

import json
import math
import os
import unittest
from unittest.mock import patch

import httpx

from grubhub_mcp import auth as auth_module
from grubhub_mcp.tools import _common
from grubhub_mcp.tools import account as account_tools
from grubhub_mcp.tools import auth as auth_tools
from grubhub_mcp.tools import cart as cart_tools
from grubhub_mcp.tools import order as order_tools
from grubhub_mcp.tools import restaurant as restaurant_tools


class FakeSession:
    def __init__(self) -> None:
        self.auth_token = "token"
        self.refresh_token = "refresh"
        self.csrf_token = "csrf"
        self.diner_udid = None
        self.is_authenticated = True

    def set_authenticated(self, session_data: dict, require_token: bool = False) -> None:
        handle = session_data.get("session_handle") or {}
        token = handle.get("access_token")
        if require_token and not token:
            raise ValueError("no token")
        self.auth_token = token or self.auth_token
        credential = session_data.get("credential") or {}
        self.diner_udid = (
            credential.get("ud_id") or credential.get("udid") or self.diner_udid
        )
        self.is_authenticated = True

    def _save(self) -> None:  # persistence is exercised in test_client.py
        pass


class FakeClient:
    def __init__(
        self,
        history_orders: list[dict] | None = None,
        history_pages: list[dict] | None = None,
    ) -> None:
        self.session = FakeSession()
        self.session.diner_udid = "diner-123"
        # ``history_pages`` lets a test serve a different payload per page;
        # ``history_orders`` is the single-page shorthand.
        self.history_pages = history_pages
        self.history_orders = history_orders or []
        self.put_calls: list[tuple[str, dict, bool]] = []
        self.get_calls: list[tuple[str, object, bool]] = []
        self.post_calls: list[tuple[str, dict | None, bool, object]] = []
        self.delete_calls: list[str] = []
        self.ensure_session_calls = 0
        # Cart responses for the place_order confirmation preview.
        self.cart_response: dict | None = None
        self.cart_error: Exception | None = None

    async def ensure_session(self) -> None:
        self.ensure_session_calls += 1

    async def put(self, path: str, data: dict | None = None, auth_required: bool = True, params=None):
        self.put_calls.append((path, data or {}, auth_required))
        if path.endswith("/profile"):
            return {}
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
        if path == f"/diners/{self.session.diner_udid}/search_listing":
            return self._search_listing(dict(params or []))
        if path.startswith("/restaurants/v4/"):
            return {"restaurant_id": path.rsplit("/", 1)[-1], "params": dict(params or {})}
        if path.startswith("/carts/"):
            if self.cart_error is not None:
                raise self.cart_error
            return self.cart_response if self.cart_response is not None else {}
        raise AssertionError(f"unexpected GET path: {path}")

    def _search_listing(self, params: dict) -> dict:
        page_num = int(params.get("pageNum", 1))
        if self.history_pages is not None:
            if 1 <= page_num <= len(self.history_pages):
                return self.history_pages[page_num - 1]
            return {"results": [], "pager": {}}
        if page_num == 1:
            return {
                "results": self.history_orders,
                "partner_results": [],
                "pager": {
                    "total_pages": 1,
                    "current_page": 1,
                    "results_size": len(self.history_orders),
                },
            }
        return {"results": [], "partner_results": [], "pager": {"total_pages": 1}}

    async def post(
        self,
        path: str,
        data: dict | None = None,
        auth_required: bool = True,
        params=None,
    ):
        self.post_calls.append((path, data, auth_required, params))
        if path.startswith("/orders/") and path.endswith("/reorder"):
            request = httpx.Request("POST", f"https://api-gtm.grubhub.com{path}")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        if path == "/carts":
            return {"id": "cart-123", "already_exists": False}
        if path.endswith("/favorites/restaurants"):
            return {"status": "ok"}
        if path.startswith("/orders/") and path.endswith("/tip"):
            return {"status": "tipped"}
        if path.startswith("/carts/") and path.endswith("/submit"):
            return {"order_id": "order-999", "status": "placed"}
        raise AssertionError(f"unexpected POST path: {path}")

    async def delete(self, path: str, auth_required: bool = True, params=None):
        self.delete_calls.append(path)
        return {}


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self, *args, **kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _register(module) -> FakeMCP:
    mcp = FakeMCP()
    module.register(mcp)
    return mcp


class AuthAndOrdersTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_otp_fetches_session_when_udid_missing(self):
        client = FakeClient()
        client.session.diner_udid = None

        await auth_module.verify_otp(client, "user@example.com", "123456")

        self.assertEqual(client.session.diner_udid, "otp-diner-456")
        self.assertEqual(client.get_calls[0][0], "/session")

    async def test_verify_otp_clears_csrf_token_after_use(self):
        client = FakeClient()

        await auth_module.verify_otp(client, "user@example.com", "123456")

        self.assertIsNone(client.session.csrf_token)

    async def test_verify_login_otp_maps_401_to_friendly_error(self):
        client = FakeClient()
        mcp = _register(auth_tools)
        request = httpx.Request("PUT", "https://api-gtm.grubhub.com/auth/confirmation_code")
        response = httpx.Response(401, request=request)

        with (
            patch("grubhub_mcp.tools.auth.get_client", return_value=client),
            patch(
                "grubhub_mcp.tools.auth.auth_module.verify_otp",
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
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
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

    async def test_get_order_returns_friendly_auth_error_when_logged_out(self):
        client = FakeClient(history_orders=[])
        client.session.is_authenticated = False
        client.session.diner_udid = None
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order"]("order-1")

        data = json.loads(raw)
        self.assertEqual(data, {"error": "Must be logged in to view order details"})

    async def test_get_order_falls_back_to_history_lookup_on_404(self):
        history_orders = [
            {"id": "order-1", "group_id": "group-1", "name": "first"},
            {"id": "order-2", "group_id": "group-2", "name": "second"},
        ]
        client = FakeClient(history_orders=history_orders)
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
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
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
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

    async def test_reorder_reports_missing_order_instead_of_raising(self):
        client = FakeClient(history_orders=[])
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["reorder"]("group-missing")

        data = json.loads(raw)
        self.assertIn("not found", data["error"])
        self.assertEqual(data["status_code"], 404)

    async def test_build_cart_payload_rejects_restaurant_without_id(self):
        with self.assertRaises(ValueError):
            order_tools._build_cart_payload_from_order(
                {
                    "restaurants": [{"name": "no id here"}],
                    "charges": {"lines": {"line_items": [{"menu_item_id": "1"}]}},
                }
            )


class OrderHistoryPaginationTests(unittest.IsolatedAsyncioTestCase):
    """Server-side pagination via /diners/{id}/search_listing.

    Adapted from upstream PR aserper/grubhub-mcp#9 by karbassi.
    """

    async def test_get_order_history_uses_server_side_pagination(self):
        pages = [
            {
                "results": [{"id": "order-1"}, {"id": "order-2"}],
                "pager": {"total_pages": 3, "current_page": 1},
            },
            {
                "results": [{"id": "order-3"}],
                "partner_results": [{"id": "partner-1"}],
                "pager": {"total_pages": 3, "current_page": 2},
            },
        ]
        client = FakeClient(history_pages=pages)
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order_history"](page_size=2, page_num=2)

        data = json.loads(raw)
        self.assertEqual([o["id"] for o in data["orders"]], ["order-3", "partner-1"])
        self.assertEqual(data["pagination"]["page_num"], 2)
        self.assertEqual(data["pagination"]["returned"], 2)
        self.assertEqual(data["pagination"]["total_pages"], 3)
        self.assertEqual(data["pagination"]["current_page"], 2)

        path, params, _ = client.get_calls[0]
        self.assertEqual(path, "/diners/diner-123/search_listing")
        # params must be a sequence of pairs so the repeated "facet" key survives
        self.assertIn(("facet", "scheduled:false"), params)
        self.assertIn(("facet", "orderType:ALL"), params)
        self.assertIn(("pageNum", 2), params)
        self.assertIn(("pageSize", 2), params)

    async def test_get_order_history_rejects_invalid_page(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await mcp.tools["get_order_history"](page_size=10, page_num=0)

        self.assertIn("page_num", json.loads(raw)["error"])

    async def test_find_order_walks_every_page(self):
        pages = [
            {"results": [{"id": "a"}], "pager": {"total_pages": 3}},
            {"results": [{"id": "b"}], "pager": {"total_pages": 3}},
            {"results": [{"id": "target", "group_id": "g"}], "pager": {"total_pages": 3}},
        ]
        client = FakeClient(history_pages=pages)

        match = await order_tools._find_order_in_history(client, "target")

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["id"], "target")
        self.assertEqual(len(client.get_calls), 3)

    async def test_find_order_stops_on_empty_page_without_pager(self):
        pages = [
            {"results": [{"id": "a"}]},  # short page, no pager
            {"results": [{"id": "b"}]},
        ]
        client = FakeClient(history_pages=pages)

        match = await order_tools._find_order_in_history(client, "nope")

        self.assertIsNone(match)
        # A short page with no pager means we are at the end.
        self.assertEqual(len(client.get_calls), 1)

    async def test_find_order_is_capped_when_pager_is_absurd(self):
        page_size = order_tools.DEFAULT_HISTORY_PAGE_SIZE
        full_page = {
            "results": [{"id": f"x-{i}"} for i in range(page_size)],
            "pager": {"total_pages": 10_000_000},
        }
        client = FakeClient(history_pages=[full_page] * 500)

        match = await order_tools._find_order_in_history(client, "nope")

        self.assertIsNone(match)
        self.assertEqual(len(client.get_calls), order_tools.MAX_HISTORY_PAGES)


class MoneyAndValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_tip_rounds_instead_of_truncating(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            await mcp.tools["set_tip"]("cart-1", 1.15)

        path, payload, _ = client.put_calls[0]
        self.assertEqual(path, "/carts/cart-1/tip")
        # int(1.15 * 100) == 114 in binary floating point.
        self.assertEqual(payload["tip_amount"], 115)

    async def test_set_tip_rejects_negative_amount(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            raw = await mcp.tools["set_tip"]("cart-1", -1.0)

        self.assertIn("negative", json.loads(raw)["error"])
        self.assertEqual(client.put_calls, [])

    async def test_set_tip_rejects_non_finite_amount(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            raw = await mcp.tools["set_tip"]("cart-1", math.inf)

        self.assertIn("finite", json.loads(raw)["error"])
        self.assertEqual(client.put_calls, [])

    async def test_post_delivery_tip_rounds(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            await mcp.tools["post_delivery_tip"]("order-1", 8.35, confirm=True)

        path, payload, _, _ = client.post_calls[0]
        self.assertEqual(path, "/orders/order-1/tip")
        self.assertEqual(payload, {"tip_amount": 835})

    async def test_add_to_cart_rejects_zero_quantity(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            raw = await mcp.tools["add_to_cart"]("cart-1", "item-1", quantity=0)

        self.assertIn("quantity", json.loads(raw)["error"])
        self.assertEqual(client.post_calls, [])

    async def test_update_cart_item_allows_zero_quantity(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            await mcp.tools["update_cart_item"]("cart-1", "line-1", 0)

        self.assertEqual(client.put_calls[0][1], {"quantity": 0})

    async def test_update_profile_without_fields_is_rejected(self):
        client = FakeClient()
        mcp = _register(account_tools)

        with patch("grubhub_mcp.tools.account.get_client", return_value=client):
            raw = await mcp.tools["update_profile"]()

        self.assertIn("Nothing to update", json.loads(raw)["error"])
        self.assertEqual(client.put_calls, [])

    async def test_add_favorite_rejects_non_numeric_id(self):
        client = FakeClient()
        mcp = _register(account_tools)

        with patch("grubhub_mcp.tools.account.get_client", return_value=client):
            raw = await mcp.tools["add_favorite"]("not-a-number")

        self.assertIn("numeric", json.loads(raw)["error"])
        self.assertEqual(client.post_calls, [])

    async def test_add_favorite_accepts_numeric_id(self):
        client = FakeClient()
        mcp = _register(account_tools)

        with patch("grubhub_mcp.tools.account.get_client", return_value=client):
            await mcp.tools["add_favorite"]("2056994")

        self.assertEqual(client.post_calls[0][1], {"restaurant_id": 2056994})

    async def test_zero_coordinates_are_not_treated_as_missing(self):
        client = FakeClient()
        mcp = _register(restaurant_tools)

        with patch("grubhub_mcp.tools.restaurant.get_client", return_value=client):
            await mcp.tools["get_menu"]("123", latitude=0.0, longitude=0.0)

        params = client.get_calls[0][1]
        self.assertEqual(params["location"], "POINT(0.0 0.0)")


class EnvVarLoginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = {
            k: os.environ.pop(k, None)
            for k in (auth_tools.EMAIL_ENV_VAR, auth_tools.PASSWORD_ENV_VAR)
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    async def test_login_uses_environment_credentials(self):
        client = FakeClient()
        client.session.diner_udid = "diner-123"
        mcp = _register(auth_tools)
        os.environ[auth_tools.EMAIL_ENV_VAR] = "env@example.com"
        os.environ[auth_tools.PASSWORD_ENV_VAR] = "s3cret"

        seen: dict[str, str] = {}

        async def fake_login(_client, email, password):
            seen["email"] = email
            seen["password"] = password
            return {}

        with (
            patch("grubhub_mcp.tools.auth.get_client", return_value=client),
            patch("grubhub_mcp.tools.auth.auth_module.login", side_effect=fake_login),
        ):
            raw = await mcp.tools["login"]()

        self.assertEqual(seen, {"email": "env@example.com", "password": "s3cret"})
        data = json.loads(raw)
        self.assertEqual(data["status"], "authenticated")
        self.assertNotIn("password", raw)

    async def test_login_without_credentials_returns_actionable_error(self):
        client = FakeClient()
        mcp = _register(auth_tools)

        with patch("grubhub_mcp.tools.auth.get_client", return_value=client):
            raw = await mcp.tools["login"]()

        self.assertIn("GRUBHUB_EMAIL", json.loads(raw)["error"])

    async def test_explicit_arguments_win_over_environment(self):
        client = FakeClient()
        client.session.diner_udid = "diner-123"
        mcp = _register(auth_tools)
        os.environ[auth_tools.EMAIL_ENV_VAR] = "env@example.com"
        os.environ[auth_tools.PASSWORD_ENV_VAR] = "envpass"

        seen: dict[str, str] = {}

        async def fake_login(_client, email, password):
            seen["email"] = email
            seen["password"] = password
            return {}

        with (
            patch("grubhub_mcp.tools.auth.get_client", return_value=client),
            patch("grubhub_mcp.tools.auth.auth_module.login", side_effect=fake_login),
        ):
            await mcp.tools["login"]("arg@example.com", "argpass")

        self.assertEqual(seen, {"email": "arg@example.com", "password": "argpass"})


RECOGNISABLE_CART = {
    "id": "cart-1",
    "restaurant_id": "11278616",
    "order_type": "DELIVERY",
    "restaurants": [{"id": "11278616", "name": "Pizza Place", "phone": "555"}],
    "lines": {"line_items": [{"name": "Margherita", "quantity": 2}]},
    "charges": {
        "total": {"amount": 2345},
        "tip": {"amount": 400},
        "lines": {"line_items": [{"name": "Margherita", "quantity": 2}]},
    },
}


class PlaceOrderConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def _tools(self, client: FakeClient):
        return _register(order_tools).tools

    async def test_unconfirmed_call_charges_nothing(self):
        client = FakeClient()
        client.cart_response = RECOGNISABLE_CART
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            raw = await tools["place_order"]("cart-1")

        data = json.loads(raw)
        self.assertEqual(data["status"], "confirmation_required")
        self.assertEqual(data["cart_id"], "cart-1")
        self.assertIn("confirm=true", data["message"])
        # Nothing was submitted.
        self.assertEqual(client.post_calls, [])
        # The cart was fetched so the model can show it to the user.
        self.assertEqual(client.get_calls[0][0], "/carts/cart-1")

    async def test_unconfirmed_call_summarises_a_recognisable_cart(self):
        client = FakeClient()
        client.cart_response = RECOGNISABLE_CART
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1"))

        summary = data["cart_summary"]
        self.assertEqual(summary["restaurant"], {"id": "11278616", "name": "Pizza Place"})
        self.assertEqual(summary["line_items"], [{"name": "Margherita", "quantity": 2}])
        self.assertEqual(summary["order_type"], "DELIVERY")
        # Money is passed through verbatim, and the duplicated line block is dropped.
        self.assertEqual(summary["charges"]["total"], {"amount": 2345})
        self.assertNotIn("lines", summary["charges"])
        self.assertNotIn("cart", data)

    async def test_unrecognisable_cart_is_returned_raw(self):
        client = FakeClient()
        client.cart_response = {"something": "unexpected"}
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1"))

        self.assertEqual(data["status"], "confirmation_required")
        self.assertEqual(data["cart"], {"something": "unexpected"})
        self.assertNotIn("cart_summary", data)

    async def test_cart_fetch_http_error_still_asks_for_confirmation(self):
        client = FakeClient()
        request = httpx.Request("GET", "https://api-gtm.grubhub.com/carts/cart-1")
        client.cart_error = httpx.HTTPStatusError(
            "gone",
            request=request,
            response=httpx.Response(404, request=request, text="no such cart"),
        )
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1"))

        self.assertEqual(data["status"], "confirmation_required")
        self.assertEqual(data["cart_error"]["status_code"], 404)
        self.assertIn("no such cart", data["cart_error"]["detail"])
        self.assertEqual(client.post_calls, [])

    async def test_cart_fetch_transport_error_still_asks_for_confirmation(self):
        client = FakeClient()
        client.cart_error = httpx.ConnectError("no route to host")
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1"))

        self.assertEqual(data["status"], "confirmation_required")
        self.assertIn("no route to host", data["cart_error"]["detail"])
        self.assertEqual(client.post_calls, [])

    async def test_confirmed_call_submits_the_cart(self):
        client = FakeClient()
        client.cart_response = RECOGNISABLE_CART
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(
                await tools["place_order"](
                    "cart-1", payment_method_id="pm-1", tip_amount=4.15, confirm=True
                )
            )

        self.assertEqual(data["order_id"], "order-999")
        path, payload, _, _ = client.post_calls[0]
        self.assertEqual(path, "/carts/cart-1/submit")
        self.assertEqual(payload, {"payment_method_id": "pm-1", "tip_amount": 415})
        # No preview fetch on the confirmed call.
        self.assertEqual(client.get_calls, [])

    async def test_preview_reports_the_tip_that_would_be_charged(self):
        client = FakeClient()
        client.cart_response = RECOGNISABLE_CART
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1", tip_amount=1.15))

        self.assertEqual(data["tip"], {"dollars": 1.15, "cents": 115})

    async def test_invalid_tip_is_rejected_before_the_preview(self):
        client = FakeClient()
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1", tip_amount=-5))

        self.assertIn("negative", data["error"])
        self.assertEqual(client.get_calls, [])
        self.assertEqual(client.post_calls, [])

    async def test_auth_guard_runs_before_the_preview(self):
        client = FakeClient()
        client.session.is_authenticated = False
        client.session.diner_udid = None
        tools = self._tools(client)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await tools["place_order"]("cart-1"))

        self.assertEqual(data, {"error": "Must be logged in to place an order"})
        self.assertEqual(client.get_calls, [])


class PostDeliveryTipConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfirmed_call_charges_nothing(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await mcp.tools["post_delivery_tip"]("order-7", 6.25))

        self.assertEqual(data["status"], "confirmation_required")
        self.assertEqual(data["order_id"], "order-7")
        self.assertEqual(data["tip"], {"dollars": 6.25, "cents": 625})
        self.assertIn("$6.25", data["message"])
        self.assertIn("confirm=true", data["message"])
        self.assertEqual(client.post_calls, [])

    async def test_confirmed_call_charges_the_tip(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(
                await mcp.tools["post_delivery_tip"]("order-7", 6.25, confirm=True)
            )

        self.assertEqual(data["status"], "tipped")
        self.assertEqual(client.post_calls[0][0], "/orders/order-7/tip")
        self.assertEqual(client.post_calls[0][1], {"tip_amount": 625})

    async def test_invalid_tip_is_rejected_before_confirmation(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(await mcp.tools["post_delivery_tip"]("order-7", -1))

        self.assertIn("negative", data["error"])
        self.assertEqual(client.post_calls, [])


class TipCapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop(_common.MAX_TIP_ENV_VAR, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(_common.MAX_TIP_ENV_VAR, None)
        else:
            os.environ[_common.MAX_TIP_ENV_VAR] = self._saved

    def test_default_cap_is_250_dollars(self):
        self.assertEqual(_common.max_tip_dollars(), 250.0)
        self.assertEqual(_common.tip_to_cents(250.0), 25_000)
        with self.assertRaises(ValueError) as ctx:
            _common.tip_to_cents(250.01)
        message = str(ctx.exception)
        self.assertIn("$250.00", message)
        self.assertIn(_common.MAX_TIP_ENV_VAR, message)

    def test_environment_variable_raises_the_cap(self):
        os.environ[_common.MAX_TIP_ENV_VAR] = "500"
        self.assertEqual(_common.max_tip_dollars(), 500.0)
        self.assertEqual(_common.tip_to_cents(300), 30_000)
        with self.assertRaises(ValueError):
            _common.tip_to_cents(500.01)

    def test_environment_variable_can_lower_the_cap(self):
        os.environ[_common.MAX_TIP_ENV_VAR] = "10.50"
        self.assertEqual(_common.tip_to_cents(10.5), 1050)
        with self.assertRaises(ValueError):
            _common.tip_to_cents(11)

    def test_invalid_environment_values_fall_back_to_the_default(self):
        for value in ("", "  ", "abc", "-5", "0", "nan", "inf", "1,000"):
            with self.subTest(value=value):
                os.environ[_common.MAX_TIP_ENV_VAR] = value
                self.assertEqual(_common.max_tip_dollars(), 250.0)

    async def test_set_tip_enforces_the_cap(self):
        client = FakeClient()
        mcp = _register(cart_tools)

        with patch("grubhub_mcp.tools.cart.get_client", return_value=client):
            data = json.loads(await mcp.tools["set_tip"]("cart-1", 1000.0))

        self.assertIn("safety cap", data["error"])
        self.assertEqual(client.put_calls, [])

    async def test_place_order_enforces_the_cap(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(
                await mcp.tools["place_order"]("cart-1", tip_amount=999, confirm=True)
            )

        self.assertIn("safety cap", data["error"])
        self.assertEqual(client.post_calls, [])

    async def test_post_delivery_tip_enforces_the_cap(self):
        client = FakeClient()
        mcp = _register(order_tools)

        with patch("grubhub_mcp.tools.order.get_client", return_value=client):
            data = json.loads(
                await mcp.tools["post_delivery_tip"]("order-1", 999, confirm=True)
            )

        self.assertIn("safety cap", data["error"])
        self.assertEqual(client.post_calls, [])


if __name__ == "__main__":
    unittest.main()
