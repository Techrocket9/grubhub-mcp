"""Tests for session persistence, token handling and the request pipeline."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

import httpx

from grubhub_mcp import client as client_module
from grubhub_mcp.client import GrubhubClient, GrubhubSession
from grubhub_mcp.tools._common import handle_api_errors, to_cents


class SessionDirTestCase(unittest.IsolatedAsyncioTestCase):
    """Base class that redirects the on-disk session to a temp directory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("GRUBHUB_SESSION_DIR")
        os.environ["GRUBHUB_SESSION_DIR"] = str(Path(self._tmp.name) / "session-dir")

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop("GRUBHUB_SESSION_DIR", None)
        else:
            os.environ["GRUBHUB_SESSION_DIR"] = self._saved
        self._tmp.cleanup()


class SessionPersistenceTests(SessionDirTestCase):
    def test_session_file_and_directory_are_owner_only(self):
        session = GrubhubSession()
        session.set_anonymous({"session_handle": {"access_token": "abc"}})

        path = client_module.session_file()
        self.assertTrue(path.exists())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_session_file_permissions_are_umask_independent(self):
        old_umask = os.umask(0o000)
        try:
            session = GrubhubSession()
            session.set_anonymous({"session_handle": {"access_token": "abc"}})
        finally:
            os.umask(old_umask)

        path = client_module.session_file()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_no_temp_files_are_left_behind(self):
        session = GrubhubSession()
        session.set_anonymous({"session_handle": {"access_token": "abc"}})

        leftovers = [p.name for p in client_module.session_dir().glob("*.tmp")]
        self.assertEqual(leftovers, [])

    def test_round_trip_restores_session(self):
        session = GrubhubSession()
        session.set_authenticated(
            {
                "session_handle": {"access_token": "abc", "refresh_token": "ref"},
                "credential": {"ud_id": "diner-9"},
            },
            require_token=True,
        )

        restored = GrubhubSession()
        self.assertEqual(restored.auth_token, "abc")
        self.assertEqual(restored.refresh_token, "ref")
        self.assertEqual(restored.diner_udid, "diner-9")
        self.assertTrue(restored.is_authenticated)

    def test_corrupt_session_file_is_ignored(self):
        directory = client_module.session_dir()
        directory.mkdir(parents=True, exist_ok=True)
        client_module.session_file().write_text("{not json at all")

        session = GrubhubSession()

        self.assertIsNone(session.auth_token)
        self.assertFalse(session.is_authenticated)

    def test_non_object_session_file_is_ignored(self):
        directory = client_module.session_dir()
        directory.mkdir(parents=True, exist_ok=True)
        client_module.session_file().write_text(json.dumps(["nope"]))

        session = GrubhubSession()

        self.assertIsNone(session.auth_token)
        self.assertFalse(session.is_authenticated)

    def test_authenticated_flag_requires_token_and_diner_id(self):
        directory = client_module.session_dir()
        directory.mkdir(parents=True, exist_ok=True)
        client_module.session_file().write_text(
            json.dumps({"is_authenticated": True, "auth_token": None, "diner_udid": None})
        )

        session = GrubhubSession()

        self.assertFalse(session.is_authenticated)

    def test_clear_removes_the_file(self):
        session = GrubhubSession()
        session.set_anonymous({"session_handle": {"access_token": "abc"}})
        self.assertTrue(client_module.session_file().exists())

        session.clear()

        self.assertFalse(client_module.session_file().exists())
        self.assertIsNone(session.auth_token)


class SessionStateTransitionTests(SessionDirTestCase):
    def _authenticated(self) -> GrubhubSession:
        session = GrubhubSession()
        session.set_authenticated(
            {
                "session_handle": {"access_token": "tok", "refresh_token": "ref"},
                "credential": {"ud_id": "diner-1"},
            },
            require_token=True,
        )
        return session

    def test_refresh_response_preserves_diner_and_refresh_token(self):
        session = self._authenticated()

        # A refresh response carries a new access token and nothing else.
        session.set_authenticated({"session_handle": {"access_token": "tok2"}})

        self.assertEqual(session.auth_token, "tok2")
        self.assertEqual(session.refresh_token, "ref")
        self.assertEqual(session.diner_udid, "diner-1")
        self.assertTrue(session.is_authenticated)

    def test_session_response_without_token_preserves_existing_token(self):
        session = self._authenticated()

        session.set_authenticated({"credential": {"ud_id": "diner-2"}})

        self.assertEqual(session.auth_token, "tok")
        self.assertEqual(session.diner_udid, "diner-2")

    def test_fresh_login_without_token_raises(self):
        session = self._authenticated()

        with self.assertRaises(ValueError):
            session.set_authenticated({"credential": {"ud_id": "x"}}, require_token=True)

    def test_authenticating_with_no_token_anywhere_raises(self):
        session = GrubhubSession()

        with self.assertRaises(ValueError):
            session.set_authenticated({})

        self.assertFalse(session.is_authenticated)

    def test_anonymous_response_without_token_raises(self):
        session = GrubhubSession()

        with self.assertRaises(ValueError):
            session.set_anonymous({"session_handle": {}})

    def test_anonymous_session_drops_the_diner_id(self):
        session = self._authenticated()

        session.set_anonymous({"session_handle": {"access_token": "anon"}})

        self.assertIsNone(session.diner_udid)
        self.assertFalse(session.is_authenticated)


def _mock_client(handler) -> GrubhubClient:
    client = GrubhubClient()
    client._http = httpx.AsyncClient(
        base_url=client_module.BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    return client


class RequestPipelineTests(SessionDirTestCase):
    async def test_authenticated_request_bootstraps_an_anonymous_session(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path == "/auth/anon":
                return httpx.Response(
                    200, json={"session_handle": {"access_token": "anon-token"}}
                )
            return httpx.Response(200, json={"ok": True})

        client = _mock_client(handler)
        try:
            # A cart call is the first thing this process does — historically it
            # went out with no bearer token at all.
            data = await client.post("/carts", data={"brand": "GRUBHUB"})
        finally:
            await client.close()

        self.assertEqual(data, {"ok": True})
        self.assertEqual([r.url.path for r in seen], ["/auth/anon", "/carts"])
        self.assertEqual(seen[1].headers["Authorization"], "Bearer anon-token")

    async def test_unauthenticated_request_does_not_bootstrap(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={"ok": True})

        client = _mock_client(handler)
        try:
            await client.post("/auth/login", data={}, auth_required=False)
        finally:
            await client.close()

        self.assertEqual(seen, ["/auth/login"])

    async def test_concurrent_calls_create_only_one_anonymous_session(self):
        import asyncio

        anon_calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal anon_calls
            if request.url.path == "/auth/anon":
                anon_calls += 1
                await asyncio.sleep(0)
                return httpx.Response(
                    200, json={"session_handle": {"access_token": "anon-token"}}
                )
            return httpx.Response(200, json={"ok": True})

        client = _mock_client(handler)
        try:
            await asyncio.gather(*(client.get(f"/carts/{i}") for i in range(5)))
        finally:
            await client.close()

        self.assertEqual(anon_calls, 1)

    async def test_401_refresh_retries_the_original_request(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/auth/refresh":
                return httpx.Response(
                    200,
                    json={"session_handle": {"access_token": "fresh", "refresh_token": "r2"}},
                )
            if request.headers.get("Authorization") == "Bearer fresh":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, json={"error": "expired"})

        client = _mock_client(handler)
        client.session.auth_token = "stale"
        client.session.refresh_token = "r1"
        client.session.diner_udid = "diner-1"
        client.session.is_authenticated = True

        try:
            data = await client.get("/orders/1")
        finally:
            await client.close()

        self.assertEqual(data, {"ok": True})
        self.assertEqual(calls, ["/orders/1", "/auth/refresh", "/orders/1"])
        # The refresh response carried no credential; the diner id must survive.
        self.assertEqual(client.session.diner_udid, "diner-1")

    async def test_failed_refresh_clears_an_expired_login(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/auth/refresh":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(401, json={"error": "expired"})

        client = _mock_client(handler)
        client.session.auth_token = "stale"
        client.session.refresh_token = "r1"
        client.session.diner_udid = "diner-1"
        client.session.is_authenticated = True

        try:
            with self.assertRaises(httpx.HTTPStatusError):
                await client.get("/orders/1")
        finally:
            await client.close()

        # The stale login is discarded so tools say "must be logged in" instead
        # of looping on 401s forever.
        self.assertFalse(client.session.is_authenticated)
        self.assertIsNone(client.session.auth_token)
        self.assertFalse(client_module.session_file().exists())

    async def test_refresh_without_new_token_is_treated_as_failure(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/auth/refresh":
                return httpx.Response(200, json={"session_handle": {}})
            return httpx.Response(401, json={"error": "expired"})

        client = _mock_client(handler)
        client.session.auth_token = "stale"
        client.session.refresh_token = "r1"
        client.session.diner_udid = "diner-1"
        client.session.is_authenticated = True

        try:
            with self.assertRaises(httpx.HTTPStatusError):
                await client.get("/orders/1")
        finally:
            await client.close()

        # One attempt, one refresh, no retry with the same dead token.
        self.assertEqual(calls, ["/orders/1", "/auth/refresh"])

    async def test_expired_anonymous_session_is_recreated(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/auth/refresh":
                return httpx.Response(400, json={})
            if request.url.path == "/auth/anon":
                return httpx.Response(
                    200, json={"session_handle": {"access_token": "anon2"}}
                )
            if request.headers.get("Authorization") == "Bearer anon2":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, json={})

        client = _mock_client(handler)
        client.session.auth_token = "old-anon"
        client.session.refresh_token = "r1"

        try:
            data = await client.get("/restaurants/v4/1")
        finally:
            await client.close()

        self.assertEqual(data, {"ok": True})
        self.assertEqual(
            calls,
            ["/restaurants/v4/1", "/auth/refresh", "/auth/anon", "/restaurants/v4/1"],
        )

    async def test_empty_and_non_json_bodies_do_not_raise(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/empty":
                return httpx.Response(204)
            return httpx.Response(200, text="<html>nope</html>")

        client = _mock_client(handler)
        client.session.auth_token = "tok"
        try:
            self.assertEqual(await client.get("/empty"), {})
            self.assertIn("raw_response", await client.get("/html"))
        finally:
            await client.close()

    async def test_authorization_header_is_omitted_when_not_required(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        client = _mock_client(handler)
        client.session.auth_token = "tok"
        try:
            await client.post("/auth/login", data={}, auth_required=False)
        finally:
            await client.close()

        self.assertNotIn("Authorization", seen[0].headers)


class ErrorHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_status_error_becomes_structured_json(self):
        request = httpx.Request(
            "POST",
            "https://api-gtm.grubhub.com/carts",
            headers={"Authorization": "Bearer super-secret-token"},
        )
        response = httpx.Response(
            422, request=request, json={"error": {"message": "bad cart"}}
        )

        @handle_api_errors
        async def failing() -> str:
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        data = json.loads(await failing())
        self.assertEqual(data["status_code"], 422)
        self.assertIn("bad cart", data["detail"])
        # The bearer token must never reach the model through an error path.
        self.assertNotIn("super-secret-token", json.dumps(data))
        self.assertNotIn("Authorization", json.dumps(data))

    async def test_detail_is_truncated(self):
        request = httpx.Request("GET", "https://api-gtm.grubhub.com/x")
        response = httpx.Response(500, request=request, text="x" * 10_000)

        @handle_api_errors
        async def failing() -> str:
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        data = json.loads(await failing())
        self.assertLess(len(data["detail"]), 2_100)
        self.assertTrue(data["detail"].endswith("(truncated)"))

    async def test_transport_error_becomes_structured_json(self):
        @handle_api_errors
        async def failing() -> str:
            raise httpx.ConnectError("no route to host")

        data = json.loads(await failing())
        self.assertIn("Could not reach the Grubhub API", data["error"])

    async def test_value_error_becomes_structured_json(self):
        @handle_api_errors
        async def failing() -> str:
            raise ValueError("call send_login_otp first")

        self.assertEqual(
            json.loads(await failing()), {"error": "call send_login_otp first"}
        )

    async def test_decorator_preserves_signature_for_schema_generation(self):
        import inspect

        @handle_api_errors
        async def sample(cart_id: str, quantity: int = 1) -> str:
            """Docstring."""
            return "{}"

        self.assertEqual(sample.__name__, "sample")
        self.assertEqual(sample.__doc__, "Docstring.")
        self.assertEqual(
            list(inspect.signature(sample).parameters), ["cart_id", "quantity"]
        )

    def test_to_cents_rounds_half_up_and_validates(self):
        self.assertEqual(to_cents(1.15), 115)
        self.assertEqual(to_cents(8.35), 835)
        self.assertEqual(to_cents(0), 0)
        with self.assertRaises(ValueError):
            to_cents(-0.01)
        with self.assertRaises(ValueError):
            to_cents(float("nan"))
        with self.assertRaises(ValueError):
            to_cents("5")


class ServerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_tools_register_with_annotations(self):
        from grubhub_mcp.server import mcp

        tools = await mcp.list_tools()
        self.assertEqual(len(tools), 36)
        self.assertTrue(all(t.annotations is not None for t in tools))

        by_name = {t.name: t for t in tools}
        self.assertTrue(by_name["place_order"].annotations.destructiveHint)
        self.assertFalse(by_name["place_order"].annotations.readOnlyHint)
        self.assertTrue(by_name["apply_gift_card"].annotations.destructiveHint)
        self.assertTrue(by_name["search_restaurants"].annotations.readOnlyHint)
        self.assertTrue(by_name["get_order_history"].annotations.readOnlyHint)
        # Ordering tools must warn about spending money in the model-facing text.
        self.assertIn("REAL MONEY", by_name["place_order"].description)


if __name__ == "__main__":
    unittest.main()
