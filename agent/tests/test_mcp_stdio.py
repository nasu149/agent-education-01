"""Protocol-level smoke test for the local stdio MCP server."""

from __future__ import annotations

import asyncio

from agent.mcp_tools import MUTATING_TOOL_NAMES, READ_ONLY_TOOL_NAMES, load_tool_catalog


def test_stdio_server_exposes_expected_tool_catalog() -> None:
    """Start the real MCP subprocess and verify tool discovery through the adapter."""
    catalog = asyncio.run(load_tool_catalog())

    assert {tool.name for tool in catalog.read_only} == READ_ONLY_TOOL_NAMES
    assert set(catalog.mutating) == MUTATING_TOOL_NAMES
