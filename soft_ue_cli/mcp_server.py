"""MCP server mode for soft-ue-cli.

Exposes CLI commands as MCP tools and skills as MCP prompts
over stdio transport using FastMCP.

The ``mcp`` package is imported at call time so this module
can be imported without mcp installed (for testing/introspection).
"""

from __future__ import annotations

import io
import json
import sys
from typing import Any

from .mcp_schema import extract_tools
from .skills import get_skill, list_skills


def _make_tool_fn(tool_name: str):
    """Create a tool handler function that forwards to call_tool()."""

    def tool_fn(**kwargs: Any) -> str:
        from . import client as _client

        # Filter out None and False (unset optional / store_true args)
        arguments = {k: v for k, v in kwargs.items() if v is not None and v is not False}
        try:
            result = _client.call_tool(tool_name, arguments)
            return json.dumps(result, indent=2, ensure_ascii=False)
        except SystemExit:
            # call_tool() prints diagnostics to stderr before exiting.
            # Capture and surface them so the MCP client gets a useful message.
            return json.dumps({"error": f"Tool '{tool_name}' failed. Check that Unreal Engine is running with SoftUEBridge enabled."})

    tool_fn.__name__ = tool_name.replace("-", "_")
    tool_fn.__qualname__ = tool_fn.__name__

    return tool_fn


def create_server():
    """Create and configure the MCP server with all tools and prompts."""
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.prompts import Prompt

    mcp = FastMCP("soft-ue-cli")

    # Register tools from argparse introspection
    for tool_def in extract_tools():
        name = tool_def["name"]
        description = tool_def["description"]

        fn = _make_tool_fn(name)
        fn.__doc__ = description

        mcp.add_tool(fn, name=name, description=description)

    # Register skills as prompts
    for skill in list_skills():
        skill_name = skill["name"]
        skill_desc = skill["description"]

        def make_prompt_fn(sn: str, sd: str):
            def prompt_fn() -> str:
                content = get_skill(sn)
                return content or f"Skill '{sn}' not found"
            prompt_fn.__name__ = sn.replace("-", "_")
            prompt_fn.__qualname__ = prompt_fn.__name__
            prompt_fn.__doc__ = sd
            return prompt_fn

        prompt = Prompt.from_function(
            make_prompt_fn(skill_name, skill_desc),
            name=skill_name,
            description=skill_desc,
        )
        mcp.add_prompt(prompt)

    return mcp


def run_server() -> None:
    """Run the MCP server over stdio transport."""
    server = create_server()
    server.run(transport="stdio")
