"""Shared test fakes for the Grubhub MCP tools.

Tests import the installed ``grubhub_mcp`` package (``uv pip install -e .``),
so this file only needs to make ``tests/`` itself importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
