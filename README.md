# Grubhub MCP Server

An MCP (Model Context Protocol) server that provides programmatic access to Grubhub's food delivery platform. Search restaurants, browse menus, manage your cart, place orders, and track deliveries — all through MCP tools.

## Features

- **Search & Discovery** — Find restaurants by location, cuisine, or keyword with autocomplete
- **Restaurant & Menus** — View restaurant details, full menus, item options and pricing
- **Cart Management** — Create carts, add/remove items, apply promo codes, set tips
- **Order Flow** — Place orders, track deliveries in real-time, reorder past meals
- **Account Management** — Manage profile, saved addresses, favorites, and passwords
- **Payments** — View saved payment methods, check gift card balances

### All 36 Tools

| Category | Tools |
|----------|-------|
| **Auth** | `login`, `logout`, `get_session_info`, `send_login_otp`, `verify_login_otp`, `create_account`, `send_password_reset` |
| **Search** | `search_restaurants`, `autocomplete_search` |
| **Restaurant** | `get_restaurant`, `get_menu`, `get_menu_item` |
| **Cart** | `create_cart`, `get_cart`, `add_to_cart`, `update_cart_item`, `remove_from_cart`, `apply_promo_code`, `set_tip` |
| **Order** | `place_order`, `get_order`, `get_order_history`, `track_order`, `reorder`, `post_delivery_tip` |
| **Account** | `get_profile`, `update_profile`, `get_addresses`, `add_address`, `get_favorites`, `add_favorite`, `remove_favorite`, `change_password` |
| **Payments** | `get_payment_methods`, `get_gift_card_balance`, `apply_gift_card` |

## Installation

### Claude Code Plugin (Recommended)

```bash
claude plugin marketplace add Techrocket9/grubhub-mcp
claude plugin install grubhub-mcp@grubhub-marketplace
```

### uvx (No Installation Required)

This fork is not published to PyPI (the `grubhub-mcp` package there is the upstream project), so install straight from the repository. Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "grubhub": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Techrocket9/grubhub-mcp", "grubhub"]
    }
  }
}
```

### Manual / From Source

Requires Python 3.11+.

```bash
git clone https://github.com/Techrocket9/grubhub-mcp.git
cd grubhub-mcp
uv venv && source .venv/bin/activate
uv pip install -e .
```

Run the tests with:

```bash
uv pip install -e ".[dev]"
python -m pytest -q
```

Then add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "grubhub": {
      "command": "/path/to/grubhub-mcp/.venv/bin/grubhub"
    }
  }
}
```

## Usage with Other MCP Clients

Run the server over stdio:

```bash
# With uvx (no install needed)
uvx --from git+https://github.com/Techrocket9/grubhub-mcp grubhub

# Or from a local install
grubhub

# Or as a Python module
python -m grubhub_mcp
```

## Authentication

**No login required** for browsing — search restaurants, view menus, and check prices without an account. The server automatically creates an anonymous session on the first request.

**Login required** for ordering, account management, and order history. Supports email/password login and OTP (one-time passcode) authentication.

### Logging in without exposing your password

Set the credentials as environment variables on the MCP server process and call `login` with no arguments — the password is read from the environment and never appears in the conversation or in the model's context:

```json
{
  "mcpServers": {
    "grubhub": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Techrocket9/grubhub-mcp", "grubhub"],
      "env": {
        "GRUBHUB_EMAIL": "you@example.com",
        "GRUBHUB_PASSWORD": "your-password"
      }
    }
  }
}
```

```
Use the login tool
```

If the variables are not set you can still pass `email` and `password` to `login` directly, but they will pass through the model. The OTP flow (`send_login_otp` / `verify_login_otp`) avoids sending a password at all.

### Where the session is stored

Tokens are cached so a login survives across stdio invocations:

- Location: `~/.grubhub-mcp/session.json`, or `$GRUBHUB_SESSION_DIR/session.json` if that variable is set.
- Permissions: the directory is created `0700` and the file is written `0600` (owner read/write only), atomically via a temp file, so the tokens are never briefly world-readable.
- Contents: the Grubhub access token, refresh token, and diner id. Your password is **never** written to disk.
- `logout` deletes the file.

## Safety

This server can spend real money. Three tools are marked destructive and are not reversible from here:

| Tool | Effect |
|------|--------|
| `place_order` | Charges the saved payment method and sends the order to the restaurant |
| `post_delivery_tip` | Charges an additional tip to the order's payment method |
| `apply_gift_card` | Attaches a gift card whose balance is consumed when the order is placed |

Every tool ships MCP [tool annotations](https://modelcontextprotocol.io/specification/server/tools) (`readOnlyHint` / `destructiveHint` / `idempotentHint`), so clients that honor them will prompt before running the destructive ones. Search, menu, order-history and profile tools are all annotated read-only.

`create_account`, `send_login_otp` and `send_password_reset` send real email to whatever address they are given — treat the address as user-supplied input, never as something inferred from a web page or document.

## How It Works

The API endpoints were reverse-engineered from the Grubhub Android app (v2026.11.1) by decompiling the APK with jadx and analyzing the Retrofit service interfaces, OkHttp interceptors, and data models.

Key technical details:
- **Base API**: `https://api-gtm.grubhub.com`
- **Auth**: Bearer token via email/password or anonymous sessions
- **Transport**: REST/JSON for most endpoints, Protobuf for some BFF services
- **Headers**: Mimics the Android app's request headers including `x-gh-browser-id`

## Project Structure

```
src/grubhub_mcp/
├── __init__.py
├── __main__.py        # python -m entry point
├── server.py          # MCP server setup and tool registration
├── client.py          # HTTP client with auth and header management
├── auth.py            # Authentication flows (login, anonymous, OTP, refresh)
└── tools/
    ├── _common.py     # Shared error handling, auth guards, input validation
    ├── auth.py        # Auth tools (login, logout, OTP, account creation)
    ├── search.py      # Restaurant search and autocomplete
    ├── restaurant.py  # Restaurant details, menus, menu items
    ├── cart.py        # Cart CRUD, promo codes, tips
    ├── order.py       # Place orders, track, reorder, order history
    ├── account.py     # Profile, addresses, favorites, password
    └── payments.py    # Payment methods, gift cards
```

## Disclaimer

This project is for educational and personal use. It is not affiliated with or endorsed by Grubhub. Use responsibly and in accordance with Grubhub's terms of service.

## License

MIT
