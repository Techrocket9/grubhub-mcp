"""Shared helpers for the Grubhub MCP tools.

Keeps error handling, auth guards and input validation identical across every
tool so the calling model always receives structured, actionable JSON instead of
an opaque transport exception.
"""

from __future__ import annotations

import functools
import json
import math
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

# How much of an error response body to pass back to the caller. Bodies are the
# API's own error payloads (never our request headers), but they can be large.
MAX_DETAIL_CHARS = 2000

# Safety net against a runaway or mistyped tip (e.g. 10 -> 1000). Raise it by
# setting the environment variable on the MCP server process.
DEFAULT_MAX_TIP_DOLLARS = 250.0
MAX_TIP_ENV_VAR = "GRUBHUB_MAX_TIP_DOLLARS"

F = TypeVar("F", bound=Callable[..., Awaitable[str]])


def json_result(payload: Any) -> str:
    return json.dumps(payload, indent=2)


def error_result(message: str, **extra: Any) -> str:
    """Build the standard structured error envelope."""
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    return json.dumps(payload, indent=2)


def _response_detail(response: httpx.Response) -> str:
    """Truncated response body. Never includes request headers or tokens."""
    try:
        text = response.text or ""
    except Exception:  # pragma: no cover - defensive
        return ""
    text = text.strip()
    if len(text) > MAX_DETAIL_CHARS:
        return text[:MAX_DETAIL_CHARS] + "... (truncated)"
    return text


def handle_api_errors(func: F) -> F:
    """Turn transport/validation failures into structured JSON tool results.

    ``functools.wraps`` keeps ``__name__``/``__doc__``/``__annotations__``
    intact, so FastMCP still derives the correct tool schema from the wrapped
    signature.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                message = (
                    "Grubhub rejected the request as unauthenticated (HTTP 401). "
                    "Log in again with the login or send_login_otp tools."
                )
            elif status == 403:
                message = "Grubhub refused the request (HTTP 403 Forbidden)."
            elif status == 404:
                message = "Grubhub could not find that resource (HTTP 404)."
            elif status == 429:
                message = "Grubhub is rate limiting the request (HTTP 429)."
            else:
                message = f"Grubhub API request failed with HTTP {status}."
            return error_result(
                message,
                status_code=status,
                detail=_response_detail(exc.response),
            )
        except httpx.HTTPError as exc:
            return error_result(
                f"Could not reach the Grubhub API: {type(exc).__name__}: {exc}"
            )
        except ValueError as exc:
            return error_result(str(exc))

    return wrapper  # type: ignore[return-value]


def require_authenticated(client: Any, action: str) -> str | None:
    """Return an error result when the session cannot perform ``action``."""
    if not client.session.is_authenticated or not client.session.diner_udid:
        return error_result(f"Must be logged in to {action}")
    return None


def to_cents(amount: Any, field: str = "tip_amount") -> int:
    """Convert a dollar amount to whole cents.

    ``int(1.15 * 100)`` truncates to 114 because of binary float
    representation; rounding is required to charge the amount the user asked
    for.
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValueError(f"{field} must be a number of dollars")
    if not math.isfinite(amount):
        raise ValueError(f"{field} must be a finite number")
    if amount < 0:
        raise ValueError(f"{field} cannot be negative")
    return int(round(amount * 100))


def max_tip_dollars() -> float:
    """Current tip ceiling in dollars, from the environment or the default.

    Parsed defensively: anything unparseable, non-finite or non-positive falls
    back to the default rather than disabling the cap.
    """
    raw = os.environ.get(MAX_TIP_ENV_VAR)
    if raw is None:
        return DEFAULT_MAX_TIP_DOLLARS
    try:
        value = float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_MAX_TIP_DOLLARS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_MAX_TIP_DOLLARS
    return value


def tip_to_cents(amount: Any, field: str = "tip_amount") -> int:
    """Convert a tip in dollars to cents, refusing implausibly large tips."""
    cents = to_cents(amount, field)
    cap = max_tip_dollars()
    if cents > int(round(cap * 100)):
        raise ValueError(
            f"{field} of ${cents / 100:,.2f} exceeds the ${cap:,.2f} safety cap. "
            "If the user really means this amount, raise the cap by setting the "
            f"{MAX_TIP_ENV_VAR} environment variable on the MCP server process."
        )
    return cents


def require_int(value: Any, field: str, minimum: int = 1, maximum: int | None = None) -> int:
    """Validate an integer argument, rejecting bools and out-of-range values."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field} must be at most {maximum}")
    return value


def require_non_empty(value: Any, field: str) -> str:
    """Validate a required string argument."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()
