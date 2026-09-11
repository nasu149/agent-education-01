"""Load MCP tools and separate observation capabilities from mutation capabilities."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


READ_ONLY_TOOL_NAMES = {
    "http_request",
    "list_containers",
    "inspect_container",
    "get_container_logs",
    "read_config",
}
MUTATING_TOOL_NAMES = {"start_container", "restart_container"}


@dataclass
class ToolCatalog:
    """Tool sets with an explicit privilege boundary."""

    read_only: list[BaseTool]
    mutating: dict[str, BaseTool]


async def load_tool_catalog() -> ToolCatalog:
    """Load tools from the local MCP server over stdio.

    The LLM only receives `read_only`. Mutation tools remain available to the
    deterministic remediation node, which is reachable only after approval.
    """

    client = MultiServerMCPClient(
        {
            "operations": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "mcp_server.server"],
            }
        }
    )
    tools = await client.get_tools()
    by_name = {tool.name: tool for tool in tools}

    missing = (READ_ONLY_TOOL_NAMES | MUTATING_TOOL_NAMES) - by_name.keys()
    if missing:
        raise RuntimeError(f"MCP server is missing required tools: {sorted(missing)}")

    return ToolCatalog(
        read_only=[by_name[name] for name in sorted(READ_ONLY_TOOL_NAMES)],
        mutating={name: by_name[name] for name in MUTATING_TOOL_NAMES},
    )
